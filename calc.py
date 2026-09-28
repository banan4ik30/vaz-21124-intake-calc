"""IntakeLab — расчётное ядро: впускной тракт атмосферного 4-тактного мотора.

Что считается (подробный вывод формул и источники — docs/METHODOLOGY.md):

1. Волновая (инерционно-волновая) настройка канала — обороты, на которых отражённая
   волна давления приходит к впускному клапану перед его закрытием (k-я гармоника).
2. Резонанс Гельмгольца «ресивер + дроссель + труба до фильтра».
3. Скорость потока и число Маха в канале, расход воздуха, скорость в дросселе.
4. Подбор длины канала под целевые обороты и проверка компоновки.

Это инженерная оценка (±10–15 %), а не 1D/3D-моделирование.
Модуль не зависит от GUI: его можно импортировать или запускать из консоли.
"""

from __future__ import annotations

import argparse
import json
import math
import sys

__version__ = "1.0.0"

# --- физические константы -------------------------------------------------
R_AIR = 287.05          # Дж/(кг·К), удельная газовая постоянная сухого воздуха
GAMMA = 1.4             # показатель адиабаты воздуха
P_ATM = 101325.0        # Па
C_EMPIRICAL = 396.0     # м/с (1300 ft/s) — константа классической формулы волновой настройки

# Концевые поправки открытого конца трубы (Levine & Schwinger 1948; Rayleigh):
END_CORR_UNFLANGED = 0.6133   # ×r — конец трубы без фланца (в коробе фильтра)
END_CORR_FLANGED = 0.8216     # ×r — конец во фланце/стенке (выход дросселя в ресивер)

THROTTLE_BODY_LEN = 0.05      # м — длина проточной части дроссельного узла

HARMONICS = (2, 3, 4, 5, 6)
# Относительная сила импульса по калькулятору Bowling's Intake Runner Computator
# (для 5–6 данных нет — только «слабее 4-й»).
PULSE_STRENGTH = {2: 10, 3: 7, 4: 4, 5: None, 6: None}

DEFAULTS = {
    "bore_mm": 82.0,
    "stroke_mm": 75.6,
    "cylinders": 4,
    "cr": 10.3,
    "ivo_btdc": 17.0,
    "ivc_abdc": 59.0,
    "air_temp_c": 40.0,
    "runner_len_mm": 500.0,
    "runner_d_mm": 34.5,
    "plenum_l": 1.5,
    "throttle_d_mm": 46.0,
    "inlet_len_mm": 400.0,
    "inlet_d_mm": 60.0,
    "rpm_min": 1500.0,
    "rpm_limit": 5500.0,
    "ve": 0.88,
    "target_rpm": 3750.0,
    "pack_min_mm": 300.0,
    "pack_max_mm": 650.0,
    "sound_model": "empirical",   # empirical | physical
}

# Эмпирические ориентиры практиков (не законы физики — см. METHODOLOGY.md, раздел 6)
RUNNER_V_RANGE = (55.0, 90.0)      # м/с, средняя скорость в канале на отсечке
RUNNER_V_DESIGN = (60.0, 75.0)     # м/с, по ним подбирается рекомендуемый диаметр
THROTTLE_V_MAX = 75.0              # м/с, средняя скорость в дросселе
PLENUM_RATIO = (0.7, 1.2, 1.8)     # границы «мало / низ-середина / середина-верх / верх»


# --- базовые формулы ------------------------------------------------------
def sound_speed(temp_c: float) -> float:
    """Скорость звука в идеальном газе: c = √(γ·R·T)."""
    return math.sqrt(GAMMA * R_AIR * (temp_c + 273.15))


def evcd_deg(ivo_btdc: float, ivc_abdc: float) -> float:
    """Угол, когда впускной клапан закрыт (EVCD), ° поворота коленвала.

    Фаза впуска = IVO + 180 + IVC; за цикл 720°, остаток — клапан закрыт.
    """
    return 720.0 - (ivo_btdc + 180.0 + ivc_abdc)


def tuned_rpm(c: float, evcd: float, length_m: float, d_m: float, k: int) -> float:
    """Обороты, на которые настроен канал на k-й гармонике.

    Пока клапан закрыт (t = EVCD / 6N секунд), волна пробегает канал туда-обратно;
    условие настройки L_eff = c·t / (4k), L_eff = L + D/2 (концевая поправка).
    Эквивалентно классической формуле L = EVCD·0.25·V·2 / (N·RV) − D/2 (дюймы, ft/s).
    """
    l_eff = length_m + d_m / 2
    return c * evcd / (24.0 * k * l_eff)


def length_for_rpm(c: float, evcd: float, rpm: float, d_m: float, k: int) -> float:
    """Обратная задача: длина канала (м) для пика на rpm на k-й гармонике."""
    return c * evcd / (24.0 * k * rpm) - d_m / 2


def helmholtz_hz(c: float, volume_m3: float, necks: list[tuple[float, float, float]]) -> float:
    """Частота резонатора Гельмгольца с горлышком из последовательных участков.

    necks — [(длина м, диаметр м, концевая поправка ×r), ...]. Инертности участков
    складываются: M = Σ (L_i + δ_i·r_i) / A_i;  f = c/(2π) · √(1 / (V·M)).
    Для одного участка сводится к классическому f = c/(2π)·√(A / (V·L_eff)).
    """
    inertance = 0.0
    for length, diam, corr in necks:
        r = diam / 2
        inertance += (length + corr * r) / (math.pi * r * r)
    return c / (2 * math.pi) * math.sqrt(1.0 / (volume_m3 * inertance))


def plenum_resonance(c: float, plenum_m3: float, th_d: float, inlet_len: float, inlet_d: float,
                     cyl: int) -> dict:
    """Резонанс «ресивер + дроссель + труба до фильтра» и обороты, где с ним
    совпадает частота впусков (cyl/2 впусков за оборот коленвала)."""
    f = helmholtz_hz(c, plenum_m3, [
        (THROTTLE_BODY_LEN, th_d, END_CORR_FLANGED),
        (inlet_len, inlet_d, END_CORR_UNFLANGED),
    ])
    return {"hz": f, "rpm": f * 60 / (cyl / 2)}


def mean_piston_speed(stroke_m: float, rpm: float) -> float:
    return 2 * stroke_m * rpm / 60


def runner_velocity(bore_m: float, d_m: float, stroke_m: float, rpm: float) -> float:
    """Средняя скорость в канале из неразрывности: v = (B/D)²·Cm."""
    return (bore_m / d_m) ** 2 * mean_piston_speed(stroke_m, rpm)


def air_mass_flow_kgh(vd_total_m3: float, rpm: float, ve: float, rho: float) -> float:
    """Расход воздуха 4-тактного мотора: ṁ = ρ·Vd·N/120·VE (кг/ч)."""
    return rho * vd_total_m3 * rpm / 120 * ve * 3600


# --- основной расчёт ------------------------------------------------------
def _num(p: dict, key: str) -> float:
    try:
        return float(p.get(key, DEFAULTS[key]))
    except (TypeError, ValueError):
        return float(DEFAULTS[key])


def normalize(params: dict | None) -> dict:
    p = dict(DEFAULTS)
    if params:
        p.update({k: v for k, v in params.items() if k in DEFAULTS and v is not None and v != ""})
    if p["sound_model"] not in ("empirical", "physical"):
        p["sound_model"] = "empirical"
    return p


def compute(params: dict | None = None) -> dict:
    p = normalize(params)

    bore = _num(p, "bore_mm") / 1000
    stroke = _num(p, "stroke_mm") / 1000
    cyl = max(1, int(_num(p, "cylinders")))
    ivo = _num(p, "ivo_btdc")
    ivc = _num(p, "ivc_abdc")
    t_c = _num(p, "air_temp_c")
    L = max(0.05, _num(p, "runner_len_mm") / 1000)
    D = max(0.01, _num(p, "runner_d_mm") / 1000)
    plenum_l = max(0.05, _num(p, "plenum_l"))
    th_d = max(0.01, _num(p, "throttle_d_mm") / 1000)
    inlet_len = max(0.0, _num(p, "inlet_len_mm") / 1000)
    inlet_d = max(0.02, _num(p, "inlet_d_mm") / 1000)
    rpm_min = max(500.0, _num(p, "rpm_min"))
    rpm_lim = max(rpm_min + 500, _num(p, "rpm_limit"))
    ve = min(1.2, max(0.4, _num(p, "ve")))
    target = max(1000.0, _num(p, "target_rpm"))
    pack_min = _num(p, "pack_min_mm")
    pack_max = _num(p, "pack_max_mm")
    model = p["sound_model"]

    evcd = evcd_deg(ivo, ivc)
    duration = 720 - evcd
    c_phys = sound_speed(t_c)
    c = C_EMPIRICAL if model == "empirical" else c_phys
    c_alt = c_phys if model == "empirical" else C_EMPIRICAL

    vd_cyl = math.pi / 4 * bore ** 2 * stroke
    vd_total = vd_cyl * cyl
    vd_total_l = vd_total * 1000
    rho = P_ATM / (R_AIR * (t_c + 273.15))
    a_runner = math.pi / 4 * D ** 2
    a_th = math.pi / 4 * th_d ** 2

    # 1. волновая настройка текущей длины
    tuning = []
    for k in HARMONICS:
        n = tuned_rpm(c, evcd, L, D, k)
        tuning.append({
            "k": k,
            "rpm": round(n),
            "rpm_alt": round(tuned_rpm(c_alt, evcd, L, D, k)),
            "strength": PULSE_STRENGTH[k],
            "in_range": rpm_min <= n <= rpm_lim,
        })
    in_range = [t for t in tuning if t["in_range"]]
    main = min(in_range, key=lambda t: t["k"]) if in_range else None
    # чувствительность: на сколько об/мин сдвигается главный пик при +10 мм длины
    sens = None
    if main:
        sens = round(tuned_rpm(c, evcd, L + 0.01, D, main["k"]) - main["rpm"])

    # 2. подбор длины под целевые обороты
    pick = []
    for k in HARMONICS:
        lm = length_for_rpm(c, evcd, target, D, k) * 1000
        pick.append({
            "k": k,
            "len_mm": round(lm),
            "len_alt_mm": round(length_for_rpm(c_alt, evcd, target, D, k) * 1000),
            "strength": PULSE_STRENGTH[k],
            "fits": pack_min <= lm <= pack_max,
        })
    fits = [x for x in pick if x["fits"]]
    best_pick = min(fits, key=lambda x: x["k"]) if fits else None

    lengths = list(range(200, 1001, 10))
    curves = [{
        "k": k,
        "pts": [round(tuned_rpm(c, evcd, l / 1000, D, k)) for l in lengths],
        "alt": [round(tuned_rpm(c_alt, evcd, l / 1000, D, k)) for l in lengths],
    } for k in HARMONICS]

    # 3. скорости и расход по оборотам
    rpm_axis = list(range(int(rpm_min // 250 * 250), int(rpm_lim) + 1, 250))
    vel, flow, th_vel = [], [], []
    for n in rpm_axis:
        vel.append(round(runner_velocity(bore, D, stroke, n), 1))
        flow.append(round(air_mass_flow_kgh(vd_total, n, ve, rho), 1))
        th_vel.append(round(vd_total * n / 120 * ve / a_th, 1))

    cm_lim = mean_piston_speed(stroke, rpm_lim)
    v_lim = runner_velocity(bore, D, stroke, rpm_lim)
    mach_lim = v_lim / c_phys
    d_rec = [round(bore * math.sqrt(cm_lim / v) * 1000, 1) for v in (RUNNER_V_DESIGN[1], RUNNER_V_DESIGN[0])]
    q_lim = vd_total * rpm_lim / 120 * ve
    th_v_lim = q_lim / a_th
    flow_lim = air_mass_flow_kgh(vd_total, rpm_lim, ve, rho)
    ratio = plenum_l / vd_total_l

    # 4. резонанс ресивера — реальный акустический резонатор, всегда физическая c
    pr = plenum_resonance(c_phys, plenum_l / 1000, th_d, inlet_len, inlet_d, cyl)
    pr_rpm = pr["rpm"]
    pr_in_range = rpm_min <= pr_rpm <= rpm_lim
    pr_sweep = [
        {"plenum_l": v, "rpm": round(plenum_resonance(c_phys, v / 1000, th_d, inlet_len, inlet_d, cyl)["rpm"])}
        for v in (1.0, 1.6, 2.4, 3.3, 4.2)
    ]

    # 5. выводы
    notes = []
    if main:
        others = ", ".join(f"{t['rpm']}" for t in in_range if t is not main)
        strength = f", сила импульса ~{main['strength']} %" if main["strength"] else ""
        notes.append(("ok", f"Канал {L*1000:.0f} мм: самый сильный пик ~{main['rpm']} об/мин "
                            f"({main['k']}-я гармоника{strength}; альт. модель ~{main['rpm_alt']})"
                            + (f"; слабее — {others} об/мин." if others else ".")
                            + f" +10 мм длины сдвигают пик на {sens} об/мин."))
    else:
        notes.append(("warn", "Ни одна гармоника (2–6) не попадает в рабочий диапазон оборотов — "
                              "длина канала не работает на вас."))
    lo, hi = RUNNER_V_RANGE
    if v_lim < lo:
        notes.append(("warn", f"Скорость в канале на отсечке {v_lim:.0f} м/с — низковата: вялый отклик "
                              f"внизу. Диаметр можно уменьшить до {d_rec[0]:.0f}–{d_rec[1]:.0f} мм."))
    elif v_lim > hi:
        notes.append(("warn", f"Скорость в канале на отсечке {v_lim:.0f} м/с (M={mach_lim:.2f}) — высоко, "
                              f"канал душит верх. Рекомендуемый диаметр {d_rec[0]:.0f}–{d_rec[1]:.0f} мм."))
    else:
        notes.append(("ok", f"Скорость в канале на отсечке {v_lim:.0f} м/с (M={mach_lim:.2f}) — "
                            f"в пределах ориентира {lo:.0f}–{hi:.0f}."))
    r1, r2, r3 = PLENUM_RATIO
    if ratio < r1:
        notes.append(("warn", f"Ресивер {plenum_l:.2f} л = {ratio:.2f}× рабочего объёма — маловат: "
                              "цилиндры будут «воровать» воздух друг у друга."))
    elif ratio <= r2:
        notes.append(("ok", f"Ресивер {ratio:.2f}× рабочего объёма — хороший отклик, акцент на низ/середину."))
    elif ratio <= r3:
        notes.append(("info", f"Ресивер {ratio:.2f}× рабочего объёма — середина/верх, отклик чуть мягче."))
    else:
        notes.append(("warn", f"Ресивер {ratio:.2f}× рабочего объёма — «верховой» объём (как спортивные "
                              "3–4 л). С короткими каналами на стоковых валах отклик внизу ухудшится."))
    if th_v_lim > THROTTLE_V_MAX:
        notes.append(("warn", f"Средняя скорость в дросселе на отсечке {th_v_lim:.0f} м/с — дроссель "
                              "начинает ограничивать."))
    else:
        notes.append(("ok", f"Дроссель {th_d*1000:.0f} мм: средняя скорость {th_v_lim:.0f} м/с — запас есть."))
    if pr_in_range:
        notes.append(("info", f"Резонанс ресивера (Гельмгольц) ~{pr_rpm:.0f} об/мин ({pr['hz']:.0f} Гц) — "
                              "небольшая добавка наполнения в этой зоне. Сдвигается объёмом ресивера "
                              "и трубой до фильтра."))
    else:
        notes.append(("info", f"Резонанс ресивера ~{pr_rpm:.0f} об/мин — вне рабочего диапазона, "
                              "на езду почти не влияет."))
    if best_pick:
        notes.append(("info", f"Для пика на {target:.0f} об/мин под ваш моторный отсек подходит "
                              f"~{best_pick['len_mm']} мм ({best_pick['k']}-я гармоника)."))
    else:
        notes.append(("warn", f"Под {target:.0f} об/мин ни одна длина не укладывается в "
                              f"{pack_min:.0f}–{pack_max:.0f} мм."))

    return {
        "version": __version__,
        "params": p,
        "engine": {
            "displacement_l": round(vd_total_l, 3),
            "cyl_cc": round(vd_cyl * 1e6, 1),
            "duration": round(duration, 1),
            "evcd": round(evcd, 1),
            "c": round(c, 1),
            "c_phys": round(c_phys, 1),
            "rho": round(rho, 3),
        },
        "tuning": tuning,
        "main": main,
        "sensitivity_rpm_per_10mm": sens,
        "pick": pick,
        "best_pick": best_pick,
        "plenum_res": {"hz": round(pr["hz"], 1), "rpm": round(pr_rpm), "in_range": pr_in_range, "sweep": pr_sweep},
        "chart_len": {"lengths": lengths, "curves": curves},
        "chart_rpm": {"rpm": rpm_axis, "vel": vel, "flow": flow, "th_vel": th_vel},
        "kpi": {
            "v_limit": round(v_lim, 1),
            "mach_limit": round(mach_lim, 3),
            "d_rec": d_rec,
            "flow_limit": round(flow_lim, 1),
            "th_v_limit": round(th_v_lim, 1),
            "plenum_ratio": round(ratio, 2),
            "runner_area_cm2": round(a_runner * 1e4, 2),
        },
        "notes": [{"level": lv, "text": tx} for lv, tx in notes],
    }


def report(result: dict) -> str:
    p, e, k = result["params"], result["engine"], result["kpi"]
    lines = [
        f"IntakeLab {result['version']} — РАСЧЁТ ВПУСКНОГО ТРАКТА (инженерная оценка ±10–15 %)",
        "=" * 70,
        f"Мотор: {p['bore_mm']}×{p['stroke_mm']} мм, {p['cylinders']} цил., "
        f"{e['displacement_l']} л, СЖ {p['cr']}",
        f"Фазы впуска: открытие {p['ivo_btdc']}° до ВМТ, закрытие {p['ivc_abdc']}° после НМТ "
        f"→ {e['duration']}°, EVCD {e['evcd']}°",
        f"Скорость звука: {e['c']} м/с ({p['sound_model']}), физическая {e['c_phys']} м/с",
        "",
        f"Канал: {p['runner_len_mm']} мм (седло клапана → вход в ресивер), Ø{p['runner_d_mm']} мм",
        f"Ресивер: {p['plenum_l']} л ({k['plenum_ratio']}× раб. объёма), дроссель Ø{p['throttle_d_mm']} мм",
        f"Труба до фильтра: {p['inlet_len_mm']} мм, Ø{p['inlet_d_mm']} мм",
        f"Резонанс ресивера (Гельмгольц): {result['plenum_res']['hz']} Гц → "
        f"~{result['plenum_res']['rpm']} об/мин",
        "",
        "Настройка текущей длины:",
    ]
    for t in result["tuning"]:
        mark = " ◄ в диапазоне" if t["in_range"] else ""
        s = f", импульс ~{t['strength']} %" if t["strength"] else ""
        lines.append(f"  {t['k']}-я гармоника: {t['rpm']} об/мин (альт. {t['rpm_alt']}{s}){mark}")
    if result["sensitivity_rpm_per_10mm"] is not None:
        lines.append(f"  Чувствительность: +10 мм длины → {result['sensitivity_rpm_per_10mm']} об/мин")
    lines += ["", f"Подбор длины под {p['target_rpm']} об/мин:"]
    for x in result["pick"]:
        mark = " ◄ влезает" if x["fits"] else ""
        lines.append(f"  {x['k']}-я гармоника: {x['len_mm']} мм (альт. {x['len_alt_mm']}){mark}")
    lines += [
        "",
        f"Скорость в канале на отсечке: {k['v_limit']} м/с (M = {k['mach_limit']}); "
        f"рекомендуемый Ø {k['d_rec'][0]}–{k['d_rec'][1]} мм",
        f"Расход воздуха на отсечке: {k['flow_limit']} кг/ч (сравнить с ДМРВ в логах)",
        f"Средняя скорость в дросселе: {k['th_v_limit']} м/с",
        "",
        "Выводы:",
    ]
    lines += [f"  • {n['text']}" for n in result["notes"]]
    return "\n".join(lines)


def _parse_set(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        key, _, val = it.partition("=")
        if key not in DEFAULTS:
            raise SystemExit(f"Неизвестный параметр: {key}. Доступны: {', '.join(DEFAULTS)}")
        out[key] = val if key == "sound_model" else float(val)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="calc.py", description="IntakeLab — расчёт впускного тракта (консоль)")
    ap.add_argument("-c", "--config", help="JSON-файл конфигурации (как сохраняет приложение)")
    ap.add_argument("-s", "--set", action="append", metavar="ключ=значение",
                    help="переопределить параметр, напр. -s runner_len_mm=450")
    ap.add_argument("--json", action="store_true", help="вывести полный результат в JSON")
    ap.add_argument("--defaults", action="store_true", help="показать параметры по умолчанию")
    a = ap.parse_args(argv)
    if a.defaults:
        print(json.dumps(DEFAULTS, ensure_ascii=False, indent=2))
        return 0
    params = {}
    if a.config:
        with open(a.config, encoding="utf-8") as fh:
            data = json.load(fh)
        params.update(data.get("params", data))
    params.update(_parse_set(a.set))
    res = compute(params)
    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else report(res))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
