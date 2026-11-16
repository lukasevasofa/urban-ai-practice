"""Единые подписи, легенды и карты показателей исследования."""

import folium
import numpy as np
import pandas as pd
from branca.colormap import LinearColormap


METRICS = {
    "land_use": ("Функциональное использование", "Преобладающая зона OSM по площади пересечения. Это фактические теги OSM, а не Генплан."),
    "buildings_count": ("Количество зданий", "Контуры зданий, отнесённые к кварталу по внутренней точке; вспомогательные строения включены."),
    "footprint_area": ("Площадь оснований зданий, м²", "Сумма площадей контуров. Показывает занятую зданиями поверхность."),
    "build_floor_area": ("Общая поэтажная площадь, м²", "Основание × модельная этажность. Не кадастровая площадь."),
    "living_area": ("Модельная жилая площадь, м²", "Для жилых зданий 90% поэтажной площади. Основа распределения населения."),
    "population": ("Модельное население, чел.", "Условное распределение ориентира 133 тыс. на 01.01.2025 по уточнённой жилой площади вне садовых зон. Не официальное население кварталов."),
    "population_density": ("Плотность населения, чел./га", "Модельное население / площадь квартала. Парки и промышленность входят в площадь территории."),
    "schools_count": ("Школы и корпуса, объектов каталога", "Записи каталога размещения школ и корпусов, включая совместное размещение. Всего 24 организации; это не число независимых зданий."),
    "capacity": ("Общедоступная вместимость школ, мест", "Муниципальная мощность основной модели. Часть значений оценена по площади / 18 м² на место; частные и специальные школы исключены."),
    "fsi": ("FSI · интенсивность застройки", "Общая поэтажная площадь / площадь квартала, м²/м². Чем выше, тем интенсивнее использование земли."),
    "gsi": ("GSI · доля застроенной земли", "Площадь оснований / площадь квартала, доля 0–1. Ноль означает отсутствие зданий."),
    "mxi": ("MXI · доля жилой площади", "Жилая площадь / общая поэтажная площадь, доля 0–1. Низкие значения — преобладание нежилой застройки."),
    "l": ("L · средняя этажность", "Поэтажная площадь / площадь оснований. Средняя этажность, взвешенная по площади основания."),
    "osr": ("OSR · открытое пространство", "Незастроенная площадь земли / поэтажная площадь. Высокое значение — больше открытой земли на м² помещений."),
    "spacematrix": ("Морфотип Spacematrix", "Готовая классификация BlocksNet: 11 кластеров по FSI, L и MXI, random_state=42. Названия переведены на русский."),
    "strelka": ("Морфотип «Стрелки»", "Готовые пороговые правила BlocksNet по этажности, интенсивности и доле жилья. Без застройки морфотип не определяется."),
    "nearest_school_minutes": ("До ближайшей муниципальной школы, мин", "Путь по пешеходной сети от узла квартала до узла фактической школьной площадки; 4,5 км/ч. Без учёта конкуренции."),
    "provision_strong": ("Конкурентная обеспеченность, доля", "Доля модельного спроса, распределённая по доступным местам за 15 минут. Спрос 120 мест на 1000 жителей. Учитывается конкуренция."),
    "unmet_demand": ("Неудовлетворённый спрос, мест", "Спрос, не обслуженный за 15 минут в конкурентной модели. Не фактическое число детей без школы."),
    "area_accessibility": ("area_accessibility · среднее время, мин", "Среднее сетевое время до всех кварталов, взвешенное по их площади. Меньше — доступнее остальная территория; это не доля доступной площади."),
    "network_snap_m": ("Привязка квартала к сети, м", "Расстояние от внутренней точки квартала до ближайшего узла основной сети. Диагностика точности, в матрицу минут не прибавляется."),
}
METRICS = {key: {"title": title, "description": description} for key, (title, description) in METRICS.items()}

TRANSLATIONS = {
    "residential": "Жилая", "business": "Общественно-деловая", "industrial": "Промышленная",
    "recreation": "Рекреационная", "agriculture": "Сельскохозяйственная / садоводство",
    "special": "Специального назначения", "transport": "Транспортная",
    "individual residential": "Индивидуальная жилая застройка", "low-rise model": "Малоэтажная типовая",
    "central model": "Центральная модель", "mid-rise microdistrict": "Среднеэтажный микрорайон",
    "mid-rise block": "Среднеэтажный квартал", "mid-rise": "Среднеэтажная",
    "high-rise soviet microdistrict": "Советский многоэтажный микрорайон",
    "high-rise modern microdistrict": "Современный многоэтажный микрорайон",
    "low-rise non-residential": "Малоэтажная нежилая", "mid-rise non-residential": "Среднеэтажная нежилая",
    "high-rise non-residential": "Многоэтажная нежилая",
}


def translate(value: object) -> str:
    """Перевести категорию или обозначить отсутствие данных."""
    if pd.isna(value):
        return "Нет данных / без застройки"
    value = str(value)
    if value in TRANSLATIONS:
        return TRANSLATIONS[value]
    for old, new in [("high-mid-rise", "Повышенной этажности"), ("high-rise", "Многоэтажная"),
                     ("mid-rise", "Среднеэтажная"), ("low-rise", "Малоэтажная"), ("tower", "Башенная"),
                     ("low-density", "низкой плотности"), ("high-density", "высокой плотности"),
                     ("non-residential", "нежилая"), ("mixed-use", "смешанная"), ("residential", "жилая")]:
        value = value.replace(old, new)
    return value


def indicator_map(blocks, indicator: str, schools=None) -> folium.Map:
    """Создать карту с русской легендой, отдельным цветом нуля и пропусков."""
    frame = blocks.to_crs(4326).copy()
    if "block_id" not in frame:
        frame["block_id"] = frame.index
    values = frame[indicator]
    categorical = not pd.api.types.is_numeric_dtype(values)
    palette = ["#dbeafe", "#93c5fd", "#3b82f6", "#0369a1", "#164e63"]
    colors = LinearColormap(palette, vmin=0, vmax=max(float(values.max()), 1)) if not categorical else None
    if indicator in ["provision_strong", "gsi", "mxi"]:
        colors = LinearColormap(["#fef08a", "#86efac", "#15803d"], vmin=0, vmax=1)
    categories = sorted(values.dropna().unique()) if categorical else []
    cat_colors = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#9333ea", "#0891b2", "#db2777",
                  "#4d7c0f", "#6d28d9", "#78716c", "#0f766e", "#e11d48", "#7c3aed"]
    mapping = {cat: cat_colors[i % len(cat_colors)] for i, cat in enumerate(categories)}
    frame["display_value"] = values.map(translate) if categorical else values.map(
        lambda v: "Нет данных" if pd.isna(v) else f"{v:,.3f}".rstrip("0").rstrip("."))
    m = folium.Map(tiles="OpenStreetMap", control_scale=True)

    def style(feature):
        value = feature["properties"][indicator]
        color = "#b8bec7" if value is None else mapping[value] if categorical else "#ffffff" if value == 0 else colors(value)
        return {"fillColor": color, "color": "#334155", "weight": 0.8, "fillOpacity": 0.73}

    folium.GeoJson(frame[["block_id", indicator, "display_value", "geometry"]], style_function=style,
        highlight_function=lambda f: {"weight": 3, "fillOpacity": 0.9},
        tooltip=folium.GeoJsonTooltip(fields=["block_id", "display_value"],
            aliases=["Квартал", METRICS[indicator]["title"]])).add_to(m)
    if schools is not None and indicator in ["capacity", "schools_count", "provision_strong", "unmet_demand", "nearest_school_minutes"]:
        for _, row in schools.to_crs(4326).iterrows():
            capacity_text = "неизвестно" if pd.isna(row.capacity) else f"{row.capacity:.0f}"
            folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4,
                color="#166534" if row.public_supply else "#6b7280", fill=True,
                tooltip=f"{row['name']}: {capacity_text} мест ({row.capacity_source})").add_to(m)
    if categorical:
        legend = "<br>".join(f'<span style="color:{color}">■</span> {translate(cat)}' for cat, color in mapping.items())
    else:
        colors.caption = METRICS[indicator]["title"]
        colors.add_to(m)
        legend = "□ Белый — ноль<br>■ Серый — нет данных"
    m.get_root().html.add_child(folium.Element(
        '<div style="position:fixed;bottom:24px;left:12px;z-index:9999;background:white;padding:10px;'
        'max-width:330px;max-height:280px;overflow:auto;font:12px Arial;border:1px solid #94a3b8">'
        f'<b>{METRICS[indicator]["title"]}</b><br>{legend}<br>Серый — нет данных / без застройки</div>'))
    bounds = frame.total_bounds
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    return m
