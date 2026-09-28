# Verification of the calculations

[Русский](../VALIDATION.md) | **English**

What confirms that the program calculates correctly. All items except the last one are automated tests in [`tests/test_calc.py`](../../tests/test_calc.py), run on every push by GitHub Actions.

```bash
python -m pytest -q
```

## 1. Physical constants

| Check | Reference | Program |
|---|---|---|
| Speed of sound, 20 °C | 343.2 m/s (handbook) | 343.2 m/s |
| Speed of sound, 0 °C | 331.3 m/s (handbook) | 331.3 m/s |
| Empirical constant | 1300 ft/s = 396.2 m/s | 396.0 m/s |
| EVCD of stock 21124 | 720 − 256 = 464° | 464° |

## 2. Agreement with the classic wave-tuning formula

The "inch" formula from tuning literature `L = EVCD·0.25·V·2/(N·RV) − D/2` with V = 1300 ft/s and the program's SI formula give the **same rpm** (within 0.1 %). Test `test_tuned_rpm_equals_classic_imperial_formula`.

## 3. The DRIVE2 formula is a special case

The Russian DRIVE2 forums use the simplification `L(mm) = 2 550 000 / N`. The program (3rd harmonic, c = 396 m/s, 256° duration, no end correction) gives:

| N, rpm | DRIVE2 | Program |
|---|---|---|
| 3000 | 850 mm | 851 mm |
| 4000 | 638 mm | 638 mm |
| 5000 | 510 mm | 510 mm |

So the forum formula is the 3rd harmonic of the same model, not a different method.

## 4. Comparison with the Bowling calculator (independent calculation)

The article [driver.top/blog/407473](https://driver.top/blog/407473/) quotes Bowling's Intake Runner Computator for a total length of 19" (482.6 mm):

| Harmonic | Bowling | Program, empirical (Ø34.5) | Program, physical (40 °C) |
|---|---|---|---|
| 2nd | 6183–7503 | 7658 (+2 % above the upper bound) | 6861 |
| 3rd | 4646–5309 | **5106** ✓ | 4574 |
| 4th | 3622–4051 | **3829** ✓ | 3430 |

The 3rd and 4th harmonics of the empirical model fall inside Bowling's ranges. Bowling's ranges lie between the empirical and physical models, i.e. inside the uncertainty bands of the program's chart. Test `test_matches_bowling_calculator_19_inch` checks this with a 3 % tolerance.

## 5. Helmholtz resonator

- For a single neck the program's formula matches the classic `f = c/(2π)·√(A/(V·L_eff))` (`test_helmholtz_single_neck_classic`).
- Two identical L/2 segments give the same frequency as one of length L: inertances add up correctly (`test_helmholtz_series_necks_add_inertance`).
- Four times the volume gives half the frequency, f ∝ 1/√V (`test_helmholtz_scaling_with_volume`).

## 6. Flow

- Air flow: 1.6 L, 6000 rpm, VE = 1, ρ = 1.2 → 345.6 kg/h, matches a hand calculation (`test_air_mass_flow`).
- Runner velocity from continuity: with B = 2D the runner velocity is exactly 4× the mean piston speed (`test_runner_velocity_continuity`).

## 7. Languages

- Russian is the default; English conclusions and report contain no Cyrillic; the language never changes the numbers (`test_english_notes_and_report`, `test_language_does_not_change_numbers`).

## 8. Stock VAZ 21124

With the stock data ([DATA_21124.md](DATA_21124.md)) — 500 mm, Ø34.5, 256° duration:
- the 3rd harmonic **4934** rpm and the 4th **3700** rpm fall into Bowling's ranges (`test_stock_21124_peaks_match_bowling`);
- owners report that the engine "wakes up" at about 3500 rpm, consistent with the 4th harmonic at ~3300–3700 (band between the models).

## What the verification does NOT prove

The tests confirm that the formulas are implemented correctly and agree with independent calculators of the same physical model. They do **not** prove that the model accurately predicts the torque curve of a particular engine — that requires measurements (ECU logs, dyno) or 1D simulation. See "Limitations" in [METHODOLOGY.md](METHODOLOGY.md).
