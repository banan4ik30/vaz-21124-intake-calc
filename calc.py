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

__version__ = "1.0.1"

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


LANGS = ("ru", "en")

# Тексты выводов и отчёта на двух языках. Плейсхолдеры подставляются через str.format.
MSG = {
    "ru": {
        "peak": "Канал {L:.0f} мм: самый сильный пик ~{rpm} об/мин ({k}-я гармоника{strength}; альт. модель ~{alt}){others}. +10 мм длины сдвигают пик на {sens} об/мин.",
        "strength": ", сила импульса ~{s} %",
        "others": "; слабее — {list} об/мин",
        "no_peak": "Ни одна гармоника (2–6) не попадает в рабочий диапазон оборотов — длина канала не работает на вас.",
        "v_low": "Скорость в канале на отсечке {v:.0f} м/с — низковата: вялый отклик внизу. Диаметр можно уменьшить до {d0:.0f}–{d1:.0f} мм.",
        "v_high": "Скорость в канале на отсечке {v:.0f} м/с (M={m:.2f}) — высоко, канал душит верх. Рекомендуемый диаметр {d0:.0f}–{d1:.0f} мм.",
        "v_ok": "Скорость в канале на отсечке {v:.0f} м/с (M={m:.2f}) — в пределах ориентира {lo:.0f}–{hi:.0f}.",
        "pl_small": "Ресивер {V:.2f} л = {r:.2f}× рабочего объёма — маловат: цилиндры будут «воровать» воздух друг у друга.",
        "pl_low": "Ресивер {r:.2f}× рабочего объёма — хороший отклик, акцент на низ/середину.",
        "pl_mid": "Ресивер {r:.2f}× рабочего объёма — середина/верх, отклик чуть мягче.",
        "pl_big": "Ресивер {r:.2f}× рабочего объёма — «верховой» объём (как спортивные 3–4 л). С короткими каналами на стоковых валах отклик внизу ухудшится.",
        "th_high": "Средняя скорость в дросселе на отсечке {v:.0f} м/с — дроссель начинает ограничивать.",
        "th_ok": "Дроссель {d:.0f} мм: средняя скорость {v:.0f} м/с — запас есть.",
        "pr_in": "Резонанс ресивера (Гельмгольц) ~{rpm:.0f} об/мин ({hz:.0f} Гц) — небольшая добавка наполнения в этой зоне. Сдвигается объёмом ресивера и трубой до фильтра.",
        "pr_out": "Резонанс ресивера ~{rpm:.0f} об/мин — вне рабочего диапазона, на езду почти не влияет.",
        "pick_ok": "Для пика на {t:.0f} об/мин под ваш моторный отсек подходит ~{L} мм ({k}-я гармоника).",
        "pick_no": "Под {t:.0f} об/мин ни одна длина не укладывается в {a:.0f}–{b:.0f} мм.",
        "r_title": "IntakeLab {v} — РАСЧЁТ ВПУСКНОГО ТРАКТА (инженерная оценка ±10–15 %)",
        "r_engine": "Мотор: {B}×{S} мм, {n} цил., {Vd} л, СЖ {cr}",
        "r_cam": "Фазы впуска: открытие {ivo}° до ВМТ, закрытие {ivc}° после НМТ → {dur}°, EVCD {evcd}°",
        "r_c": "Скорость звука: {c} м/с ({model}), физическая {cp} м/с",
        "r_runner": "Канал: {L} мм (седло клапана → вход в ресивер), Ø{D} мм",
        "r_plenum": "Ресивер: {V} л ({r}× раб. объёма), дроссель Ø{th} мм",
        "r_inlet": "Труба до фильтра: {L} мм, Ø{D} мм",
        "r_pres": "Резонанс ресивера (Гельмгольц): {hz} Гц → ~{rpm} об/мин",
        "r_tuning": "Настройка текущей длины:",
        "r_harm": "  {k}-я гармоника: {rpm} об/мин (альт. {alt}{s}){mark}",
        "r_pulse": ", импульс ~{s} %",
        "r_inrange": " ◄ в диапазоне",
        "r_sens": "  Чувствительность: +10 мм длины → {s} об/мин",
        "r_pick": "Подбор длины под {t} об/мин:",
        "r_pickrow": "  {k}-я гармоника: {L} мм (альт. {alt}){mark}",
        "r_fits": " ◄ влезает",
        "r_vel": "Скорость в канале на отсечке: {v} м/с (M = {m}); рекомендуемый Ø {d0}–{d1} мм",
        "r_flow": "Расход воздуха на отсечке: {f} кг/ч (сравнить с ДМРВ в логах)",
        "r_th": "Средняя скорость в дросселе: {v} м/с",
        "r_notes": "Выводы:",
    },
    "en": {
        "peak": "Runner {L:.0f} mm: strongest peak ~{rpm} rpm (harmonic #{k}{strength}; alt. model ~{alt}){others}. +10 mm of length moves the peak by {sens} rpm.",
        "strength": ", pulse strength ~{s} %",
        "others": "; weaker ones at {list} rpm",
        "no_peak": "No harmonic (2nd–6th) falls into the working rpm range — the runner length is not working for you.",
        "v_low": "Runner velocity at the rev limit is {v:.0f} m/s — rather low: sluggish low-end response. The diameter can be reduced to {d0:.0f}–{d1:.0f} mm.",
        "v_high": "Runner velocity at the rev limit is {v:.0f} m/s (M={m:.2f}) — high, the runner chokes the top end. Recommended diameter {d0:.0f}–{d1:.0f} mm.",
        "v_ok": "Runner velocity at the rev limit is {v:.0f} m/s (M={m:.2f}) — within the {lo:.0f}–{hi:.0f} m/s guideline.",
        "pl_small": "Plenum {V:.2f} L = {r:.2f}× displacement — too small: the cylinders will rob air from each other.",
        "pl_low": "Plenum {r:.2f}× displacement — good response, emphasis on the low/mid range.",
        "pl_mid": "Plenum {r:.2f}× displacement — mid/top range, slightly softer response.",
        "pl_big": "Plenum {r:.2f}× displacement — a top-end volume (like 3–4 L race plenums). With short runners on stock cams the low-end response will suffer.",
        "th_high": "Mean throttle velocity at the rev limit is {v:.0f} m/s — the throttle starts to restrict.",
        "th_ok": "Throttle {d:.0f} mm: mean velocity {v:.0f} m/s — there is headroom.",
        "pr_in": "Plenum (Helmholtz) resonance ~{rpm:.0f} rpm ({hz:.0f} Hz) — a small filling bonus in this area. It is shifted by the plenum volume and the air-filter pipe.",
        "pr_out": "Plenum resonance ~{rpm:.0f} rpm — outside the working range, it hardly affects driving.",
        "pick_ok": "For a peak at {t:.0f} rpm, ~{L} mm fits your engine bay (harmonic #{k}).",
        "pick_no": "For {t:.0f} rpm no length fits into {a:.0f}–{b:.0f} mm.",
        "r_title": "IntakeLab {v} — INTAKE TRACT CALCULATION (engineering estimate ±10–15 %)",
        "r_engine": "Engine: {B}×{S} mm, {n} cyl., {Vd} L, CR {cr}",
        "r_cam": "Intake timing: opens {ivo}° BTDC, closes {ivc}° ABDC → {dur}°, EVCD {evcd}°",
        "r_c": "Speed of sound: {c} m/s ({model}), physical {cp} m/s",
        "r_runner": "Runner: {L} mm (valve seat → plenum entry), Ø{D} mm",
        "r_plenum": "Plenum: {V} L ({r}× displacement), throttle Ø{th} mm",
        "r_inlet": "Air-filter pipe: {L} mm, Ø{D} mm",
        "r_pres": "Plenum (Helmholtz) resonance: {hz} Hz → ~{rpm} rpm",
        "r_tuning": "Tuning of the current length:",
        "r_harm": "  Harmonic #{k}: {rpm} rpm (alt. {alt}{s}){mark}",
        "r_pulse": ", pulse ~{s} %",
        "r_inrange": " ◄ in range",
        "r_sens": "  Sensitivity: +10 mm of length → {s} rpm",
        "r_pick": "Length for a peak at {t} rpm:",
        "r_pickrow": "  Harmonic #{k}: {L} mm (alt. {alt}){mark}",
        "r_fits": " ◄ fits",
        "r_vel": "Runner velocity at the rev limit: {v} m/s (M = {m}); recommended Ø {d0}–{d1} mm",
        "r_flow": "Air flow at the rev limit: {f} kg/h (compare with the MAF reading in ECU logs)",
        "r_th": "Mean throttle velocity: {v} m/s",
        "r_notes": "Conclusions:",
    },
}


def _lang(params: dict | None) -> str:
    lang = (params or {}).get("lang", "ru")
    return lang if lang in LANGS else "ru"


def compute(params: dict | None = None) -> dict:
    p = normalize(params)
    lang = _lang(params)
    M = MSG[lang]

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
        notes.append(("ok", M["peak"].format(
            L=L * 1000, rpm=main["rpm"], k=main["k"], alt=main["rpm_alt"], sens=sens,
            strength=M["strength"].format(s=main["strength"]) if main["strength"] else "",
            others=M["others"].format(list=others) if others else "")))
    else:
        notes.append(("warn", M["no_peak"]))
    lo, hi = RUNNER_V_RANGE
    if v_lim < lo:
        notes.append(("warn", M["v_low"].format(v=v_lim, d0=d_rec[0], d1=d_rec[1])))
    elif v_lim > hi:
        notes.append(("warn", M["v_high"].format(v=v_lim, m=mach_lim, d0=d_rec[0], d1=d_rec[1])))
    else:
        notes.append(("ok", M["v_ok"].format(v=v_lim, m=mach_lim, lo=lo, hi=hi)))
    r1, r2, r3 = PLENUM_RATIO
    if ratio < r1:
        notes.append(("warn", M["pl_small"].format(V=plenum_l, r=ratio)))
    elif ratio <= r2:
        notes.append(("ok", M["pl_low"].format(r=ratio)))
    elif ratio <= r3:
        notes.append(("info", M["pl_mid"].format(r=ratio)))
    else:
        notes.append(("warn", M["pl_big"].format(r=ratio)))
    if th_v_lim > THROTTLE_V_MAX:
        notes.append(("warn", M["th_high"].format(v=th_v_lim)))
    else:
        notes.append(("ok", M["th_ok"].format(d=th_d * 1000, v=th_v_lim)))
    if pr_in_range:
        notes.append(("info", M["pr_in"].format(rpm=pr_rpm, hz=pr["hz"])))
    else:
        notes.append(("info", M["pr_out"].format(rpm=pr_rpm)))
    if best_pick:
        notes.append(("info", M["pick_ok"].format(t=target, L=best_pick["len_mm"], k=best_pick["k"])))
    else:
        notes.append(("warn", M["pick_no"].format(t=target, a=pack_min, b=pack_max)))

    return {
        "version": __version__,
        "lang": lang,
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
    M = MSG[result.get("lang", "ru")]
    pr = result["plenum_res"]
    lines = [
        M["r_title"].format(v=result["version"]), "=" * 70,
        M["r_engine"].format(B=p["bore_mm"], S=p["stroke_mm"], n=p["cylinders"], Vd=e["displacement_l"], cr=p["cr"]),
        M["r_cam"].format(ivo=p["ivo_btdc"], ivc=p["ivc_abdc"], dur=e["duration"], evcd=e["evcd"]),
        M["r_c"].format(c=e["c"], model=p["sound_model"], cp=e["c_phys"]),
        "",
        M["r_runner"].format(L=p["runner_len_mm"], D=p["runner_d_mm"]),
        M["r_plenum"].format(V=p["plenum_l"], r=k["plenum_ratio"], th=p["throttle_d_mm"]),
        M["r_inlet"].format(L=p["inlet_len_mm"], D=p["inlet_d_mm"]),
        M["r_pres"].format(hz=pr["hz"], rpm=pr["rpm"]),
        "",
        M["r_tuning"],
    ]
    for t in result["tuning"]:
        lines.append(M["r_harm"].format(k=t["k"], rpm=t["rpm"], alt=t["rpm_alt"],
                                        s=M["r_pulse"].format(s=t["strength"]) if t["strength"] else "",
                                        mark=M["r_inrange"] if t["in_range"] else ""))
    if result["sensitivity_rpm_per_10mm"] is not None:
        lines.append(M["r_sens"].format(s=result["sensitivity_rpm_per_10mm"]))
    lines += ["", M["r_pick"].format(t=p["target_rpm"])]
    for x in result["pick"]:
        lines.append(M["r_pickrow"].format(k=x["k"], L=x["len_mm"], alt=x["len_alt_mm"],
                                           mark=M["r_fits"] if x["fits"] else ""))
    lines += [
        "",
        M["r_vel"].format(v=k["v_limit"], m=k["mach_limit"], d0=k["d_rec"][0], d1=k["d_rec"][1]),
        M["r_flow"].format(f=k["flow_limit"]),
        M["r_th"].format(v=k["th_v_limit"]),
        "",
        M["r_notes"],
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
    ap.add_argument("--lang", choices=LANGS, default="ru", help="язык выводов и отчёта / output language")
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
    params["lang"] = a.lang
    res = compute(params)
    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else report(res))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
