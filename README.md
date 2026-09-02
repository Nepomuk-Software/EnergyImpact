# Energy Impact for Omarchy

Which processes are drawing power, in the bar. Quiet until you open it.

*(Deutsche Fassung: [README.de.md](README.de.md).)*

On battery the panel ranks apps by CPU time and shows **~W** as a share of
pack draw. If the kernel lets this user read RAPL `energy_uj`, that number
is CPU-package energy instead. On AC without RAPL there is no honest system
watt figure — charging current is not draw — so only CPU share is listed.

No root helper, no daemon. A short `/proc` sample runs in Python and exits.

## Install

```bash
omarchy plugin add https://github.com/Nepomuk-Software/EnergyImpact.git --enable
```

The icon lands on the right. Move it with:

```bash
omarchy bar move io.github.nepomuk-software.energyimpact --section right
```

## What you get

- **Bar** — a bolt. Dim on AC, solid on battery, accent when something looks
  like a hog. Nothing in the label.
- **Panel** — pack watts (on battery), then the top processes grouped by
  executable name, with CPU share and ~W when a watt source exists.
- **Honest remainder** — display, discrete GPU and idle are *not* attributed
  to Chrome. The caption says so.

## What it is not

It is not a calorimeter, not `powertop`, and not a replacement for
`omarchy.power`. Activity Monitor already does a full process table with
optional RAPL watts while its panel is open. This widget is the Mac battery
menu extra: a short list, only the energy question.

## Settings

`omarchy bar set io.github.nepomuk-software.energyimpact <key> <value>`

| Key | Default | Effect |
|---|---|---|
| `hideOnAc` | `false` | hide the icon on wall power |
| `intervalSec` | `4` | sample period while the panel is open |
| `idleIntervalSec` | `15` | sample period while it is closed (so the bolt can light up) |

## Uninstall

```bash
omarchy plugin remove io.github.nepomuk-software.energyimpact
```

## License

MIT — see [LICENSE](LICENSE).
