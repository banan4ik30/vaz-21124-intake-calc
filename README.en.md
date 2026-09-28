# Intake manifold calculator based on the VAZ 21124 engine

[Русский](README.md) | **English**

A Windows desktop app that helps design the **intake plenum** (manifold) of a naturally aspirated four-stroke engine. The defaults describe the **VAZ 21124 1.6 16V** (Lada 110/112/Priora family), but every parameter can be changed, so it works for other engines too. The interface is available in **Russian and English** (RU | EN switch in the header).

![Screenshot](docs/screenshot_en.png)

> ⚠️ This is an **engineering estimate** with roughly ±10–15 % uncertainty, not a gas-dynamics simulation. It helps you pick a starting runner length and plenum volume and compare variants. The final answer comes from before/after ECU logs, a dyno or 1D simulation. See the [methodology](docs/en/METHODOLOGY.md).

## What it calculates

| What | Why | How |
|---|---|---|
| **Runner length tuning** | At which rpm the reflected pressure wave "tops up" the cylinder | Wave tuning, harmonics 2–6 ([methodology §2](docs/en/METHODOLOGY.md#2-runner-length-wave-tuning)) |
| **Length for a target rpm** | Which length gives a peak at the chosen rpm and whether it fits under the hood | Inverse of the same model |
| **Plenum resonance** | How the plenum volume and the air-filter pipe shift the plenum resonance | Helmholtz resonator with exact end corrections ([§3](docs/en/METHODOLOGY.md#3-plenum-resonance-helmholtz)) |
| **Runner velocity and Mach number** | Whether the runner is too wide or too narrow | Continuity equation ([§4](docs/en/METHODOLOGY.md#4-flow)) |
| **Air flow** | Compare with the MAF sensor in ECU logs | ṁ = ρ·Vd·N/120·VE |
| **Throttle velocity** | Whether the throttle restricts | Same, through the throttle area |

## Features

- Everything recalculates instantly; the runner length can be changed by **dragging the marker** on the chart.
- **Two speed-of-sound models** — empirical (as in the classic calculators) and physical. The band between them shows the method uncertainty.
- **Comparison mode** "◎ Baseline": remember the current setup, change parameters and see before/after on the charts and cards.
- **Save and load configurations** as `.json`.
- **Report** as `.txt` with all figures and conclusions (in the selected language).
- **Russian / English** interface, conclusions and report.
- **Command-line mode** without the UI — handy for scripts and parameter sweeps.

## Installation

### Ready-made exe

Download `VAZ21124-IntakeCalc.exe` from [Releases](../../releases) and run it — no installation needed. Requires Windows 10/11 with Microsoft Edge WebView2 (preinstalled on Windows 11).

### From source

```bash
git clone https://github.com/banan4ik30/vaz-21124-intake-calc.git
cd vaz-21124-intake-calc
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

### Command line

```bash
python calc.py --lang en                                     # report for stock 21124
python calc.py --lang en -s runner_len_mm=620 -s plenum_l=2.0
python calc.py -c my_config.json --json                      # full result as JSON
python calc.py --defaults                                    # list of parameters
```

## How to use

1. Press **"Stock 21124"** to load the engine defaults (sources — [DATA_21124.md](docs/en/DATA_21124.md)).
2. Press **"◎ Baseline"** to remember the stock setup.
3. Change the runner length, plenum volume, diameter and watch:
   - **main peak** — the strongest harmonic in the working range;
   - **length for a target rpm** — which length gives the peak and whether it fits (hatched — packaging range);
   - **conclusions** — automatic review of the setup.
4. Save a good variant to `.json` and export the report.

**Runner length** is the full path **from the valve seat to the plenum entry**: head port + lower manifold + plenum runner.

## Project structure

| File | Responsibility |
|---|---|
| [`calc.py`](calc.py) | **Calculation core.** All formulas, constants, empirical thresholds and the RU/EN texts. UI-independent, also a CLI tool |
| [`app.py`](app.py) | Window shell (pywebview + Edge WebView2): bridge between the UI and `calc.py`, files, settings |
| [`ui/index.html`](ui/index.html) | Interface: fields, SVG charts, animations, RU/EN dictionary. One file, no external dependencies |
| [`dev_server.py`](dev_server.py) | Dev server to work on the UI in a normal browser (`?dev=1`, `&lang=en`) |
| [`tests/test_calc.py`](tests/test_calc.py) | Automated tests against reference values |
| [`docs/en/METHODOLOGY.md`](docs/en/METHODOLOGY.md) | Methodology: formulas, derivation, limitations, sources |
| [`docs/en/VALIDATION.md`](docs/en/VALIDATION.md) | Evidence that the calculations are correct |
| [`docs/en/DATA_21124.md`](docs/en/DATA_21124.md) | VAZ 21124 input data with sources |
| [`build.ps1`](build.ps1) | Builds the exe with PyInstaller |
| `.github/workflows/` | CI: tests on every push, exe release on a `v*` tag |

## Verification

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests check the program against reference values, the classic wave-tuning formula, the simplified DRIVE2 formula, the independent Bowling calculator and the RU/EN output. Details — [VALIDATION.md](docs/en/VALIDATION.md).

## Building the exe

```powershell
.\build.ps1
```

Output: `dist\VAZ21124-IntakeCalc.exe`. A release with the exe is built automatically when a `v*` tag is pushed.

## Limitations

- One-dimensional model: bends, taper, entry shape, cylinder interaction and the exhaust are not modelled.
- Harmonic strength is approximate (from the Bowling calculator).
- "OK / not OK" thresholds are practitioners' guidelines, not laws of physics ([methodology §6](docs/en/METHODOLOGY.md#6-empirical-guidelines-not-laws-of-physics)).
- Part of the 21124 input data is estimated; the reliability of every figure is stated in [DATA_21124.md](docs/en/DATA_21124.md).

## License

[MIT](LICENSE) — free to use, modify and distribute, including commercially, as long as the copyright notice is kept. The software is provided "as is", without warranty.
