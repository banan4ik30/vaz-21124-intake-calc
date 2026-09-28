"""Проверки расчётного ядра по независимым опорным значениям.

Источники опорных значений — docs/VALIDATION.md.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import calc  # noqa: E402

INCH = 0.0254
FTS = 0.3048


# --- физика ------------------------------------------------------------------
def test_sound_speed_matches_reference():
    # Справочное значение для сухого воздуха при 20 °C — 343.2 м/с
    assert calc.sound_speed(20.0) == pytest.approx(343.2, abs=0.3)
    # при 0 °C — 331.3 м/с
    assert calc.sound_speed(0.0) == pytest.approx(331.3, abs=0.3)


def test_evcd_stock_21124():
    # Сток 21124: впуск открывается 17° до ВМТ, закрывается 59° после НМТ -> фаза 256°
    assert calc.evcd_deg(17, 59) == pytest.approx(720 - 256)


def test_empirical_constant_is_1300_fts():
    assert calc.C_EMPIRICAL == pytest.approx(1300 * FTS, abs=0.5)


# --- волновая настройка --------------------------------------------------------
def test_tuned_rpm_equals_classic_imperial_formula():
    """L[in] = EVCD·0.25·V·2 / (N·RV) − D/2, V = 1300 ft/s — классическая форма."""
    evcd, d_in, rpm, rv = 464.0, 1.5, 4000.0, 4
    l_in = evcd * 0.25 * 1300 * 2 / (rpm * rv) - d_in / 2
    n = calc.tuned_rpm(1300 * FTS, evcd, l_in * INCH, d_in * INCH, rv)
    assert n == pytest.approx(rpm, rel=1e-3)


@pytest.mark.parametrize("k", calc.HARMONICS)
def test_length_and_rpm_are_inverse(k):
    c, evcd, d = 396.0, 464.0, 0.035
    L = calc.length_for_rpm(c, evcd, 3700.0, d, k)
    assert calc.tuned_rpm(c, evcd, L, d, k) == pytest.approx(3700.0, rel=1e-9)


def test_drive2_formula_is_third_harmonic():
    """Формула с DRIVE2 «L(мм) = 2 550 000 / n» — это 3-я гармоника при c = 396 м/с,
    фазе 256° и без концевой поправки."""
    for n in (3000, 4000, 5000):
        L = calc.length_for_rpm(396.0, 464.0, n, 0.0, 3) * 1000
        assert L == pytest.approx(2_550_000 / n, rel=0.01)


def test_matches_bowling_calculator_19_inch():
    """Bowling's Intake Runner Computator для 19" (из статьи driver.top/blog/407473):
    3-я гармоника 4646–5309, 4-я 3622–4051 об/мин. Наш расчёт (эмпирическая c,
    фаза 256°, Ø34.5) должен попадать в эти диапазоны с допуском 3 %."""
    L = 19 * INCH
    n3 = calc.tuned_rpm(396.0, 464.0, L, 0.0345, 3)
    n4 = calc.tuned_rpm(396.0, 464.0, L, 0.0345, 4)
    assert 4646 * 0.97 <= n3 <= 5309 * 1.03
    assert 3622 * 0.97 <= n4 <= 4051 * 1.03


# --- Гельмгольц ------------------------------------------------------------------
def test_helmholtz_single_neck_classic():
    c, V, L, D = 343.0, 1.0e-3, 0.08, 0.03
    r = D / 2
    A = math.pi * r * r
    expected = c / (2 * math.pi) * math.sqrt(A / (V * (L + 0.6133 * r)))
    got = calc.helmholtz_hz(c, V, [(L, D, calc.END_CORR_UNFLANGED)])
    assert got == pytest.approx(expected, rel=1e-9)


def test_helmholtz_series_necks_add_inertance():
    """Два одинаковых участка по L/2 без поправок = один участок длиной L."""
    c, V, D = 343.0, 2e-3, 0.05
    one = calc.helmholtz_hz(c, V, [(0.4, D, 0.0)])
    two = calc.helmholtz_hz(c, V, [(0.2, D, 0.0), (0.2, D, 0.0)])
    assert one == pytest.approx(two, rel=1e-12)


def test_helmholtz_scaling_with_volume():
    """f ∝ 1/√V: вчетверо больший объём — вдвое ниже частота."""
    necks = [(0.3, 0.06, calc.END_CORR_UNFLANGED)]
    f1 = calc.helmholtz_hz(343.0, 1e-3, necks)
    f4 = calc.helmholtz_hz(343.0, 4e-3, necks)
    assert f1 / f4 == pytest.approx(2.0, rel=1e-9)


# --- потоки ----------------------------------------------------------------------
def test_air_mass_flow():
    # 1.6 л, 6000 об/мин, VE = 1, ρ = 1.2 -> 1.6e-3·6000/120·1.2·3600 = 345.6 кг/ч
    assert calc.air_mass_flow_kgh(1.6e-3, 6000, 1.0, 1.2) == pytest.approx(345.6, rel=1e-9)


def test_runner_velocity_continuity():
    # (B/D)^2 · Cm: B = 2D -> скорость в 4 раза больше средней скорости поршня
    cm = calc.mean_piston_speed(0.08, 6000)
    assert cm == pytest.approx(16.0)
    assert calc.runner_velocity(0.08, 0.04, 0.08, 6000) == pytest.approx(64.0)


# --- интеграция ------------------------------------------------------------------
def test_stock_21124_peaks_match_bowling():
    """Сток 21124 (500 мм, Ø34.5, фаза 256°): 3-я гармоника (самая сильная в диапазоне
    до 5500) и 4-я попадают в диапазоны калькулятора Bowling для ~19"."""
    r = calc.compute()
    by_k = {t["k"]: t["rpm"] for t in r["tuning"]}
    assert r["main"]["k"] == 3
    assert 4646 <= by_k[3] <= 5309
    assert 3622 <= by_k[4] <= 4051
    assert r["engine"]["displacement_l"] == pytest.approx(1.597, abs=0.002)


def test_compute_is_robust_to_bad_input():
    r = calc.compute({"runner_len_mm": "abc", "plenum_l": None, "unknown": 5, "sound_model": "xxx"})
    assert r["params"]["sound_model"] == "empirical"
    assert "unknown" not in r["params"]
    assert r["tuning"]


def test_report_renders():
    text = calc.report(calc.compute())
    assert "гармоника" in text and "Выводы" in text


def test_cli_json(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"params": {"runner_len_mm": 450}}), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(ROOT / "calc.py"), "-c", str(cfg), "-s", "plenum_l=2.0", "--json"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    data = json.loads(out)
    assert data["params"]["runner_len_mm"] == 450
    assert data["params"]["plenum_l"] == 2.0
