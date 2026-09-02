#!/usr/bin/env python3
"""Attribute battery or RAPL watts to processes by CPU time.

No root, no daemon. RAPL is used only when energy_uj is readable.
On AC without RAPL, the list is CPU share only — charging current is
not system draw.
"""

from __future__ import annotations

import argparse
import glob
import os
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


def significant(rows: list[dict], pack_w: float | None, onbattery: bool) -> bool:
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
        "significant": significant(rows, bat["pack_w"] if bat["onbattery"] else None, bat["onbattery"]),
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
