# Calculation methodology

[Русский](../METHODOLOGY.md) | **English**

This document describes **every formula** the program uses: where it comes from, what the inputs mean and where it stops being valid. Calculation code — [`calc.py`](../../calc.py), tests — [`tests/test_calc.py`](../../tests/test_calc.py), comparison with external data — [VALIDATION.md](VALIDATION.md).

> **Status of the results.** This is an engineering estimate with roughly ±10–15 % uncertainty. It is good for choosing a starting runner length and plenum volume and for comparing variants. Exact answers come from 1D gas-dynamics simulation (GT-Power, Ricardo WAVE, EngMod4T, OpenWAM) and measurements on the engine (before/after ECU logs, dyno).

Notation: `N` — engine speed, rpm; `c` — speed of sound, m/s; `L` — runner length, m; `D` — runner diameter, m; `B` — bore; `S` — stroke; `i` — number of cylinders.

---

## 1. Speed of sound

For air as an ideal gas:

```
c = √(γ · R · T)
```

`γ = 1.4`, `R = 287.05 J/(kg·K)`, `T` — intake air temperature, K. At 20 °C this gives 343.2 m/s, at 40 °C — 354.7 m/s. A standard gas-dynamics result [1, ch. 7], [3].

The program offers **two speed-of-sound models** (switch in the header):

| Model | c | Why |
|---|---|---|
| **Empirical** | 396 m/s (= 1300 ft/s) | The constant of the classic wave-tuning formula and of calculators based on it. It empirically accounts for the intake being hotter than ambient and the wave travelling through moving gas |
| **Physical** | √(γRT) at the given temperature | The "honest" speed of sound without calibration |

Real peaks usually lie **between** the two models, so on the chart each harmonic is drawn as a band between them — the band width is the method uncertainty.

---

## 2. Runner length wave tuning

### Physics

When the intake valve opens, the descending piston creates a **rarefaction wave** in the runner. It travels to the plenum at the speed of sound. At the plenum entry (open end, sudden area increase) the wave is reflected **with the opposite sign** and returns to the valve as a **pressure wave**. If the pressure wave arrives just before the valve closes, it pushes an extra charge into the cylinder — inertial (wave) ram charging [1, ch. 7.6], [2].

The wave runs back and forth many times and decays at every reflection, so one length is "in tune" at several engine speeds — these are the **harmonics**. The lower the harmonic number `k`, the fewer trips the wave has made and the stronger the effect.

### Formula

Time while the intake valve is closed:

```
EVCD = 720° − (IVO + 180° + IVC)        [crank degrees]
t    = EVCD / (6·N)                      [s]   (the crank turns 6·N degrees per second)
```

`IVO` — intake opening before TDC, `IVC` — closing after BDC. For stock 21124: 17° and 59°, duration 256°, EVCD = 464°.

Tuning condition for harmonic k: during `t` the wave travels `4·k·L_eff`:

```
L_eff = c · t / (4k)   ⇒   N = c · EVCD / (24 · k · L_eff),     L_eff = L + D/2
```

`D/2` is the end correction: the wave reflects slightly beyond the geometric end of the pipe.

This is **exactly the same formula** that is widely used in tuning literature and online calculators (variants exist; this one goes back to D. Vizard's method [4]):

```
L[inches] = EVCD · 0.25 · V · 2 / (N · RV) − D/2,     V = 1300 ft/s,  RV — harmonic number
```

Equivalence is checked by `test_tuned_rpm_equals_classic_imperial_formula`.

The Russian forum (DRIVE2) formula `L(mm) = 2 550 000 / N` is the 3rd harmonic at c = 396 m/s, 256° duration and no end correction (`test_drive2_formula_is_third_harmonic`).

### Harmonic strength

Relative pulse strength is taken from Bowling's Intake Runner Computator: 2nd ≈ 10 %, 3rd ≈ 7 %, 4th ≈ 4 %. There is no numeric data for the 5th and 6th; the program shows "< 4 %". This is an **order of magnitude**, not an exact filling gain: the real gain depends on entry shape, friction, plenum volume and cylinder interaction.

The "main peak" is the **lowest-numbered (strongest) harmonic** that falls into the working rpm range.

### Sensitivity

The program shows how many rpm the main peak moves when the runner is 10 mm longer. For stock 21124 it is ≈ −95 rpm on the 3rd harmonic — hence the required accuracy of measurements: a 20–30 mm length error is already 200–300 rpm of peak shift.

### What the runner length includes

`L` is the **full path from the valve seat to the plenum entry**: head port + lower manifold (injector module) + plenum runner. For 21124 ≈ 500 mm (see [DATA_21124.md](DATA_21124.md)).

### Limitations

- One-dimensional model: plane wave, constant-area runner. Taper, bends and entry shape change the wave speed and strength.
- Cylinder interaction through the plenum is ignored.
- Valve overlap and the exhaust system are ignored.
- The real volumetric-efficiency curve is the sum of all effects. The peaks show **where the length helps**, not a finished torque curve.

---

## 3. Plenum resonance (Helmholtz)

### Physics

The plenum volume with its "neck" (throttle + filter pipe) forms a Helmholtz resonator, like a bottle. The air in the neck is the mass, the air in the volume is the spring. Cylinders draw air in pulses, `i/2` times per crank revolution. When the pulse frequency matches the resonator frequency, the plenum pressure oscillates in step with the intake events and filling increases slightly [1, ch. 7.6], [5].

### Formula

Classic Helmholtz resonator [6]:

```
f = c/(2π) · √( A / (V · L_eff) )
```

Our neck consists of two segments in series: the throttle body (50 mm long, throttle diameter) and the filter pipe. For segments in series the **inertances** `M = L_eff/A` add up:

```
M = (L_throttle + δ_f · r_throttle) / A_throttle  +  (L_pipe + δ_o · r_pipe) / A_pipe
f = c/(2π) · √( 1 / (V · M) )
N_resonance = 60 · f / (i/2)
```

End corrections:
- `δ_o = 0.6133` — unflanged open pipe end (in the air box), exact solution by Levine & Schwinger [7];
- `δ_f = 0.8216` — flanged end (throttle exit into the plenum wall), Norris & Sheng [8].

The **physical** speed of sound is always used here: this is a real acoustic resonator, the empirical wave-formula calibration does not apply.

### Limitations

- Lumped-parameter model: valid while the resonator is much smaller than the wavelength. For a 1.5 L plenum at ~100 Hz (λ ≈ 3.5 m) this holds.
- Runners and cylinders are not part of this model (Engelman's approach [5] treats cylinder + runner as a separate resonator).
- The plenum-resonance effect is usually smaller than that of the correct runner length.

---

## 4. Flow

### Air flow

A four-stroke engine has one intake event per cylinder every 2 revolutions [1, ch. 2]:

```
ṁ = ρ · Vd · N / 120 · ηv        [kg/s]  (×3600 → kg/h)
ρ = p / (R·T)
```

`Vd` — displacement, `ηv` — volumetric efficiency (VE). The kg/h figure can be compared directly with the MAF reading in ECU logs.

### Mean runner velocity

From continuity — everything the piston displaces passes through the runner:

```
Cm = 2 · S · N / 60                   — mean piston speed
v  = (B/D)² · Cm                      — mean runner velocity during the intake stroke
M  = v / c                            — Mach number
```

This is the **mean** velocity over the intake stroke; the instantaneous peak is about π/2 higher.

### Mean throttle velocity

```
v_throttle = Vd · N / 120 · ηv / A_throttle
```

---

## 5. Length for a target rpm

Inverse of section 2:

```
L = c · EVCD / (24 · k · N_target) − D/2
```

Calculated for every harmonic; variants that fit into the packaging range (what really fits under the hood) are marked.

---

## 6. Empirical guidelines (not laws of physics)

The program highlights values in green or yellow using guidelines common in intake development. These are **conventions**, not derivations. All of them are constants at the top of `calc.py` and are easy to change.

| Guideline | Value | Meaning |
|---|---|---|
| Mean runner velocity at the rev limit | 55–90 m/s | Lower — runner too wide, weak wave, sluggish response. Higher — losses grow, the runner chokes the top end. 60–75 m/s is used to suggest a diameter |
| Mean throttle velocity | up to 75 m/s | Higher — the throttle starts to restrict filling |
| Plenum / displacement | < 0.7 too small; 0.7–1.2 low/mid; 1.2–1.8 mid/top; > 1.8 "top-end" | Guideline for plenums with short runners. OEM manifolds with long runners may have larger volumes |

To assess flow restriction the literature uses the intake-valve Mach index (Livengood & Taylor [9]): above Z ≈ 0.6 volumetric efficiency drops sharply. It needs the valve diameter and flow coefficient, so the program does not compute it; the runner Mach number is shown as a guideline.

---

## Sources

1. Heywood J. B. *Internal Combustion Engine Fundamentals.* McGraw-Hill, 1988 (2nd ed. 2018). Ch. 2 (engine parameters), ch. 7 (intake, volumetric efficiency, ram and wave charging).
2. Blair G. P. *Design and Simulation of Four-Stroke Engines.* SAE International, 1999. Unsteady gas dynamics of intake and exhaust.
3. Kinsler L. E., Frey A. R., Coppens A. B., Sanders J. V. *Fundamentals of Acoustics*, 4th ed. Wiley, 2000. Speed of sound, Helmholtz resonator.
4. Vizard D. *How to Build Horsepower.* S-A Design / CarTech. Wave-tuning formula in the "inch" form.
5. Engelman H. W. *Design of a Tuned Intake Manifold.* ASME Paper 73-WA/DGP-2, 1973. Helmholtz model of the intake.
6. Rayleigh J. W. S. *The Theory of Sound*, Vol. 2. Macmillan, 1896. Helmholtz resonator.
7. Levine H., Schwinger J. *On the Radiation of Sound from an Unflanged Circular Pipe.* Physical Review 73(4), 383–406, 1948. End correction 0.6133·r.
8. Norris A. N., Sheng I. C. *Acoustic radiation from a circular pipe with an infinite flange.* Journal of Sound and Vibration 135(1), 85–93, 1989. End correction 0.8216·r.
9. Taylor C. F. *The Internal-Combustion Engine in Theory and Practice*, Vol. 1. MIT Press, 1985. Intake-valve Mach index (Livengood & Taylor).
10. Bowling's Intake Runner Computator. Online wave-tuning calculator; the result for 19" is quoted in [driver.top/blog/407473](https://driver.top/blog/407473/).
