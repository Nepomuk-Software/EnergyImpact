#!/usr/bin/env python3
"""Attribute battery or RAPL watts to processes by CPU time.

Also reads fan RPM, CPU/GPU temperatures and GPU load from hwmon
(and nvidia-smi if there is no hwmon GPU). No root, no daemon.
RAPL is used only when energy_uj is readable. On AC without RAPL,
the process list is CPU share only — charging current is not draw.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import time
from pathlib import Path

TICK = os.sysconf("SC_CLK_TCK") or 100
MAX_ROWS = 8
MAX_NAME = 48


def clamp_name(value: str) -> str:
    text = "".join(ch for ch in str(value) if ch >= " ")
    return text[:MAX_NAME]


def parse_stat(text: str) -> tuple[int, str, int] | None:
    lpar = text.find("(")
    rpar = text.rfind(")")
    if lpar <= 0 or rpar <= lpar:
        return None
    try:
        pid = int(text[:lpar].strip())
        comm = text[lpar + 1 : rpar]
        rest = text[rpar + 1 :].split()
        utime = int(rest[11])
        stime = int(rest[12])
    except (ValueError, IndexError):
        return None
    return pid, comm, utime + stime


def parse_cpu_total(text: str) -> tuple[int, int] | None:
    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()
        try:
            nums = [int(x) for x in parts[1:11]]
        except ValueError:
            return None
        # user nice system idle iowait irq softirq steal guest guest_nice
        while len(nums) < 10:
            nums.append(0)
        total = sum(nums[:8])  # exclude guest (already in user)
        idle = nums[3] + nums[4]
        return total, idle
    return None


def read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def process_name(pid: int, comm: str) -> str:
    try:
        exe = os.readlink("/proc/%d/exe" % pid)
        exe = exe.split(" (deleted)")[0]
        base = os.path.basename(exe)
        if base:
            return clamp_name(base)
    except OSError:
        pass
    return clamp_name(comm)


def is_kernel(pid: int) -> bool:
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            return handle.read() == b""
    except OSError:
        return True


def snapshot_processes() -> dict[int, tuple[str, int]]:
    out: dict[int, tuple[str, int]] = {}
    for path in glob.glob("/proc/[0-9]*/stat"):
        text = read_text(path)
        if not text:
            continue
        parsed = parse_stat(text)
        if not parsed:
            continue
        pid, comm, ticks = parsed
        if is_kernel(pid):
            continue
        out[pid] = (process_name(pid, comm), ticks)
    return out


def snapshot_cpu() -> tuple[int, int] | None:
    text = read_text("/proc/stat")
    if not text:
        return None
    return parse_cpu_total(text)


def battery_paths() -> list[Path]:
    root = Path("/sys/class/power_supply")
    if not root.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(root.iterdir()):
        try:
            kind = (entry / "type").read_text().strip()
        except OSError:
            continue
        if kind == "Battery":
            found.append(entry)
    return found


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def battery_sample() -> dict:
    out = {
        "present": False,
        "onbattery": False,
        "status": "",
        "pack_w": None,
        "percent": None,
    }
    bats = battery_paths()
    if not bats:
        return out
    bat = bats[0]
    out["present"] = True
    status = ""
    try:
        status = (bat / "status").read_text().strip()
    except OSError:
        status = ""
    out["status"] = status
    cap = read_int(bat / "capacity")
    if cap is not None:
        out["percent"] = cap
    out["onbattery"] = status.lower() == "discharging"
    watts = None
    power_now = read_int(bat / "power_now")
    if power_now is not None:
        watts = abs(power_now) / 1e6
    else:
        voltage = read_int(bat / "voltage_now")
        current = read_int(bat / "current_now")
        if voltage is not None and current is not None:
            watts = abs(voltage * current) / 1e12
    if watts is not None:
        out["pack_w"] = watts
    return out


HWMON_ROOT = Path("/sys/class/hwmon")
DRM_ROOT = Path("/sys/class/drm")
GPU_CHIPS = {"amdgpu", "nouveau", "i915", "xe"}


def read_hwmon_tree(root: Path | None = None) -> list[dict]:
    base = root or HWMON_ROOT
    chips: list[dict] = []
    if not base.is_dir():
        return chips
    for entry in sorted(base.iterdir()):
        try:
            name = (entry / "name").read_text().strip()
        except OSError:
            continue
        chip = {"name": name, "path": str(entry.resolve()) if entry.exists() else str(entry), "temps": [], "fans": [], "power_w": None, "freq_mhz": None}
        for temp in sorted(entry.glob("temp*_input")):
            idx = temp.name[4:].split("_")[0]
            milli = read_int(temp)
            if milli is None:
                continue
            label = ""
            try:
                label = (entry / ("temp%s_label" % idx)).read_text().strip()
            except OSError:
                label = ""
            chip["temps"].append({"c": milli / 1000.0, "label": label or ("temp" + idx)})
        for fan in sorted(entry.glob("fan*_input")):
            rpm = read_int(fan)
            if rpm is None or rpm <= 0:
                continue
            chip["fans"].append(rpm)
        power = read_int(entry / "power1_input")
        if power is None:
            power = read_int(entry / "power1_average")
        if power is not None and power >= 0:
            chip["power_w"] = power / 1e6
        freq = read_int(entry / "freq1_input")
        if freq is not None and freq > 0:
            chip["freq_mhz"] = freq / 1e6 if freq > 10000 else float(freq)
        chips.append(chip)
    return chips


def cpu_temp_c(chips: list[dict]) -> float | None:
    preferred = []
    fallback = []
    for chip in chips:
        lname = chip["name"].lower()
        cpuish = lname in ("k10temp", "coretemp", "zenpower", "cpu_thermal", "cpu-thermal")
        for temp in chip["temps"]:
            label = (temp["label"] or "").lower()
            if "tctl" in label or "tdie" in label or label == "package id 0":
                preferred.append(temp["c"])
            elif cpuish:
                fallback.append(temp["c"])
            elif "cpu" in label and "ddr" not in label:
                fallback.append(temp["c"])
    if preferred:
        return max(preferred)
    if fallback:
        return max(fallback)
    return None


def fan_rpm(chips: list[dict]) -> tuple[int | None, int]:
    seen: set[int] = set()
    for chip in chips:
        for rpm in chip["fans"]:
            seen.add(int(round(rpm / 50.0) * 50))
    if not seen:
        return None, 0
    return max(seen), len(seen)


def drm_busy_percent(drm_root: Path | None = None) -> int | None:
    base = drm_root or DRM_ROOT
    if not base.is_dir():
        return None
    for card in sorted(base.glob("card[0-9]*")):
        if "-" in card.name:
            continue
        path = card / "device" / "gpu_busy_percent"
        value = read_int(path)
        if value is not None:
            return max(0, min(100, value))
    return None


def gpu_info(chips: list[dict], busy: int | None) -> dict:
    gpu = {
        "name": "",
        "w": None,
        "temp_c": None,
        "busy": busy,
        "mhz": None,
    }
    for chip in chips:
        if chip["name"].lower() not in GPU_CHIPS:
            continue
        gpu["name"] = chip["name"]
        gpu["w"] = chip["power_w"]
        gpu["mhz"] = chip["freq_mhz"]
        if chip["temps"]:
            gpu["temp_c"] = chip["temps"][0]["c"]
        break
    return gpu


def nvidia_smi_gpu() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,power.draw,utilization.gpu,clocks.sm",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=0.4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return None
    parts = [p.strip() for p in line[0].split(",")]
    if len(parts) < 5:
        return None

    def num(raw: str):
        try:
            return float(raw)
        except ValueError:
            return None

    return {
        "name": clamp_name(parts[0].split()[0] if parts[0] else "nvidia"),
        "temp_c": num(parts[1]),
        "w": num(parts[2]),
        "busy": int(num(parts[3]) or 0) if num(parts[3]) is not None else None,
        "mhz": num(parts[4]),
    }


def hardware_sample(hwmon_root: Path | None = None, drm_root: Path | None = None) -> dict:
    chips = read_hwmon_tree(hwmon_root)
    rpm, fan_n = fan_rpm(chips)
    gpu = gpu_info(chips, drm_busy_percent(drm_root))
    if not gpu["name"]:
        nv = nvidia_smi_gpu()
        if nv:
            gpu = nv
    return {
        "cpu_temp_c": cpu_temp_c(chips),
        "fan_rpm": rpm,
        "fan_n": fan_n,
        "gpu_name": gpu["name"],
        "gpu_w": gpu["w"],
        "gpu_temp_c": gpu["temp_c"],
        "gpu_busy": gpu["busy"],
        "gpu_mhz": gpu["mhz"],
    }


def rapl_energy_uj() -> int | None:
    root = Path("/sys/class/powercap")
    if not root.is_dir():
        return None
    for name in ("intel-rapl:0", "intel-rapl:0:0"):
        path = root / name / "energy_uj"
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            continue
    for path in root.glob("*/energy_uj"):
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            continue
    return None


def group_deltas(
    first: dict[int, tuple[str, int]],
    second: dict[int, tuple[str, int]],
) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for pid, (name, ticks1) in first.items():
        later = second.get(pid)
        if not later:
            continue
        name2, ticks2 = later
        delta = ticks2 - ticks1
        if delta <= 0:
            continue
        label = name2 or name
        row = grouped.get(label)
        if not row:
            row = {"name": label, "ticks": 0, "n": 0}
            grouped[label] = row
        row["ticks"] += delta
        row["n"] += 1
    return grouped


def attribute(
    grouped: dict[str, dict],
    total_delta: int,
    watts: float | None,
    limit: int = MAX_ROWS,
) -> list[dict]:
    rows = sorted(grouped.values(), key=lambda r: r["ticks"], reverse=True)
    out = []
    for row in rows:
        if len(out) >= limit:
            break
        share = row["ticks"] / total_delta if total_delta > 0 else 0.0
        cpu_pct = 100.0 * share
        if cpu_pct < 0.4 and (watts is None or (watts * share) < 0.15):
            continue
        item = {
            "name": row["name"],
            "cpu": cpu_pct,
            "n": row["n"],
            "watts": (watts * share) if watts is not None else None,
        }
        out.append(item)
    return out


def significant(rows: list[dict], pack_w: float | None, onbattery: bool, hw: dict | None = None) -> bool:
    hw = hw or {}
    if hw.get("gpu_busy") is not None and hw["gpu_busy"] >= 70:
        return True
    if hw.get("fan_rpm") is not None and hw["fan_rpm"] >= 5000:
        return True
    if not onbattery:
        return False
    for row in rows:
        w = row.get("watts")
        if w is not None and w >= 2.0:
            return True
        if row.get("cpu", 0) >= 12.0:
            return True
    if pack_w is not None and pack_w >= 18.0:
        return True
    return False


def sample(interval: float = 0.7) -> dict:
    cpu1 = snapshot_cpu()
    proc1 = snapshot_processes()
    rapl1 = rapl_energy_uj()
    t1 = time.monotonic()
    time.sleep(max(0.2, interval))
    cpu2 = snapshot_cpu()
    proc2 = snapshot_processes()
    rapl2 = rapl_energy_uj()
    t2 = time.monotonic()
    bat = battery_sample()

    total_delta = 0
    idle_delta = 0
    if cpu1 and cpu2:
        total_delta = max(0, cpu2[0] - cpu1[0])
        idle_delta = max(0, cpu2[1] - cpu1[1])

    rapl_w = None
    dt = t2 - t1
    if rapl1 is not None and rapl2 is not None and dt > 0:
        du = rapl2 - rapl1
        if du < 0:
            du = 0
        rapl_w = (du / 1e6) / dt

    source = "none"
    watts = None
    if rapl_w is not None:
        watts = rapl_w
        source = "rapl"
    elif bat["onbattery"] and bat["pack_w"] is not None:
        watts = bat["pack_w"]
        source = "battery"

    grouped = group_deltas(proc1, proc2)
    rows = attribute(grouped, total_delta, watts)
    hw = hardware_sample()
    return {
        "present": bat["present"],
        "onbattery": bat["onbattery"],
        "status": bat["status"],
        "percent": bat["percent"],
        "pack_w": bat["pack_w"] if bat["onbattery"] else None,
        "rapl_w": rapl_w,
        "source": source,
        "total_delta": total_delta,
        "idle_delta": idle_delta,
        "dt": dt,
        "rows": rows,
        "cpu_temp_c": hw["cpu_temp_c"],
        "fan_rpm": hw["fan_rpm"],
        "fan_n": hw["fan_n"],
        "gpu_name": hw["gpu_name"],
        "gpu_w": hw["gpu_w"],
        "gpu_temp_c": hw["gpu_temp_c"],
        "gpu_busy": hw["gpu_busy"],
        "gpu_mhz": hw["gpu_mhz"],
        "significant": significant(rows, bat["pack_w"] if bat["onbattery"] else None, bat["onbattery"], hw),
    }


def emit(result: dict) -> None:
    def kv(key: str, value) -> None:
        if value is None or value is False:
            text = ""
        elif value is True:
            text = "1"
        elif isinstance(value, float):
            text = "%.3f" % value
        else:
            text = str(value)
        print("%s=%s" % (key, text))

    kv("present", "1" if result["present"] else "0")
    kv("onbattery", "1" if result["onbattery"] else "0")
    kv("status", result["status"] or "")
    kv("percent", result["percent"] if result["percent"] is not None else "")
    kv("pack_w", result["pack_w"])
    kv("rapl_w", result["rapl_w"])
    kv("source", result["source"])
    kv("significant", "1" if result["significant"] else "0")
    kv("dt", result["dt"])
    kv("cpu_temp_c", result.get("cpu_temp_c"))
    kv("fan_rpm", result.get("fan_rpm"))
    kv("fan_n", result.get("fan_n") or 0)
    kv("gpu_name", result.get("gpu_name") or "")
    kv("gpu_w", result.get("gpu_w"))
    kv("gpu_temp_c", result.get("gpu_temp_c"))
    kv("gpu_busy", result.get("gpu_busy"))
    kv("gpu_mhz", result.get("gpu_mhz"))
    for row in result["rows"]:
        watts = "" if row["watts"] is None else ("%.2f" % row["watts"])
        print("row=%s\t%.2f\t%s\t%d" % (row["name"], row["cpu"], watts, row["n"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=0.7)
    args = parser.parse_args()
    emit(sample(args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
