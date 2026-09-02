# Energy Impact für Omarchy

Welche Prozesse ziehen Strom, in der Bar. Ruhig, bis du aufklappst.

*(English version: [README.md](README.md) — die maßgebliche Fassung.)*

Auf Akku sortiert das Panel nach CPU-Zeit und zeigt **~W** als Anteil am
Pack-Zug. Wenn der Kernel `energy_uj` (RAPL) für diesen User lesbar macht,
ist das CPU-Package-Energie. An der Steckdose ohne RAPL gibt es keine ehrliche
System-Wattzahl — Ladestrom ist kein Verbrauch — deshalb nur CPU-Anteil.

Kein Root-Helfer, kein Daemon. Ein kurzer `/proc`-Sample in Python, dann Ende.

## Installation

```bash
omarchy plugin add https://github.com/Nepomuk-Software/EnergyImpact.git --enable
```

## Was du bekommst

- **Bar** — ein Blitz. Matt an AC, voll auf Akku, Akzent wenn etwas hoggt.
- **Panel** — Pack-Watt (auf Akku), dann **CPU-Temp, GPU-Last/Watt/Temp,
  Lüfter-RPM**, dann die Top-Prozesse nach Executable.
- **Ehrlicher Rest** — Prozess-~W ist CPU-Zeit-Anteil am Pack oder RAPL.
  GPU-PPT kommt vom Chip-Sensor und landet nicht bei Chrome.

## Settings

`omarchy bar set io.github.nepomuk-software.energyimpact <key> <value>`

| Key | Default | Wirkung |
|---|---|---|
| `hideOnAc` | `false` | Icon an der Steckdose ausblenden |
| `intervalSec` | `4` | Sample-Intervall bei offenem Panel |
| `idleIntervalSec` | `15` | bei geschlossenem Panel |

## Deinstallation

```bash
omarchy plugin remove io.github.nepomuk-software.energyimpact
```

## Lizenz

MIT — siehe [LICENSE](LICENSE).
