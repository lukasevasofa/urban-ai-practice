"""Точечная проверка атрибутов и прозрачная калибровка населения Обнинска."""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape


def revise_attributes(buildings: gpd.GeoDataFrame, data: Path) -> gpd.GeoDataFrame:
    """Уточнить только восстановленные этажи жилья и подтверждённую ошибку назначения."""
    buildings = buildings.copy()
    buildings["revision_note"] = "без точечной корректировки"
    samson = buildings.osm_key.eq("relation/21910049")
    buildings.loc[samson, "is_living"] = False
    buildings.loc[samson, "use_source"] = "уточнение: ТЦ Самсон, Комарова, 1"
    buildings.loc[samson, "number_of_floors"] = 1.0
    buildings.loc[samson, "floors_source"] = "ТЦ Самсон: 1 этаж по карточке объекта, не официальный реестр"
    buildings.loc[samson, "revision_note"] = "исключено ошибочно назначенное жильё; 9 → 1 этаж"
    explicit_living = buildings.building.isin(
        ["apartments", "residential", "house", "detached", "semidetached_house", "terrace", "dormitory"])
    # Магазин в явно жилом доме не превращает весь многоквартирный дом в нежилой.
    restore = explicit_living & ~buildings.is_living
    buildings.loc[restore, "is_living"] = True
    buildings.loc[restore, "use_source"] = "жилой тип OSM; общественная функция может быть встроенной"
    buildings.loc[restore, "revision_note"] = "сохранено жильё при встроенной общественной функции"

    raw_levels = pd.to_numeric(buildings.levels_raw, errors="coerce")
    observed = buildings[raw_levels.between(1, 60) & buildings.is_living].copy()
    observed["observed_levels"] = raw_levels.loc[observed.index]
    missing = buildings.is_living & buildings.floors_source.str.startswith(("медиана", "типовая"))
    for bid in buildings.index[missing]:
        row = buildings.loc[bid]
        # Малые дома сравниваются с малыми домами, большие — с многоквартирной застройкой.
        if row.footprint_area < 300:
            types = ["house", "detached", "semidetached_house", "terrace"]
        else:
            types = ["apartments", "residential", "dormitory", "terrace"]
        analogs = observed[observed.building.isin(types)
            & observed.footprint_area.between(row.footprint_area * 0.5, row.footprint_area * 2)]
        if pd.notna(row.zone):
            analogs = analogs[analogs.zone.eq(row.zone)]
        distance = analogs.geometry.distance(row.geometry.representative_point())
        nearest = distance[distance <= 500].nsmallest(5).index
        if len(nearest) >= 3:
            floors = float(max(1, round(analogs.loc[nearest, "observed_levels"].median())))
            if floors != row.number_of_floors:
                buildings.at[bid, "revision_note"] = f"этажи по сопоставимым наблюдениям: {row.number_of_floors:g} → {floors:g}"
            buildings.at[bid, "number_of_floors"] = floors
            buildings.at[bid, "floors_source"] = "проверка: 3–5 жилых аналогов ×0,5–2 площади до 500 м"
    return buildings


def calibrate_population(buildings: gpd.GeoDataFrame, data: Path) -> gpd.GeoDataFrame:
    """Сохранить три варианта и распределить округлённый городской ориентир по весам жилья."""
    buildings = buildings.copy()
    original = gpd.read_parquet(data / "population_initial/buildings_model.parquet").set_index("osm_key")
    buildings["population_initial"] = buildings.osm_key.map(original.population).astype(int)
    buildings["population_before_seasonality"] = buildings.population.fillna(0).astype(int)
    buildings["seasonal_garden"] = buildings.zone.eq("allotments")
    # Не меняем физическое жилое назначение садовых домов: меняется лишь постоянная заселённость.
    buildings["population_uncalibrated"] = buildings.population_before_seasonality.where(
        ~buildings.seasonal_garden, 0)

    city_record = json.loads((data / "boundary_nominatim.json").read_text())[0]
    municipal_record = json.loads((data / "municipality_nominatim.json").read_text())[0]
    assert municipal_record["osm_id"] == 1192998 and city_record["osm_id"] == 3396088
    city, municipality = shape(city_record["geojson"]), shape(municipal_record["geojson"])
    assert city.equals(municipality), "Для калибровки требуется совпадение городского и муниципального контуров OSM"
    # Общую площадь территории не используем ни как вес, ни для масштабирования населения.
    target = 133000
    weights = buildings.living_area.where(buildings.is_living & ~buildings.seasonal_garden, 0)
    expected = weights / weights.sum() * target
    population = np.floor(expected).astype(int)
    remainder = target - int(population.sum())
    # Наибольшие остатки сохраняют целочисленный итог без добавления жителей нежилым объектам.
    winners = (expected - population).sort_values(ascending=False, kind="stable").index[:remainder]
    population.loc[winners] += 1
    buildings["population"] = population
    buildings["population_model"] = population
    buildings["population_source"] = "модельное распределение ориентира 133000 на 01.01.2025 по жилой площади"
    scope = {
        "city_osm_relation": 3396088, "municipality_osm_relation": 1192998,
        "osm_polygons_equal": True, "official_population": target, "official_date": "2025-01-01",
        "official_value_rounded": True,
        "official_source": "https://obninsk.ru/obninsk/economic-development/stat/",
        "crosscheck": "Росстат, Города России 2024: город и округ Обнинск имеют одинаковую численность 132,5 тыс. на 01.01.2024",
        "crosscheck_url": "https://rosstat.gov.ru/storage/mediabank/Region_Goroda_2024.pdf",
        "limitation": "Совпадение проверено по OSM, а не по юридическому цифровому контуру. Площадь 55,03 км² в другом документе не согласуется с OSM. Разница дат статистики 2025 и геометрии/застройки OSM 2026 сохраняется.",
        "calibration_status": "Условная учебная калибровка общей численности, не подтверждение фактических жителей зданий",
        "territorial_area_scaling": False, "weights": "жилая площадь вне садовых зон",
        "permanent_garden_occupancy": 0,
        "seasonality_assumption": "Сценарий постоянного населения: садовая зона не получает постоянных жителей; фактическая регистрация неизвестна",
    }
    (data / "population_scope_check.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2))
    garden_original = original.zone.eq("allotments")
    scenarios = pd.DataFrame([
        ["Первоначальная модель", int(original.population.sum())],
        ["Только исключение садов из первоначальной модели", int(original.loc[~garden_original, "population"].sum())],
        ["Уточнённые атрибуты, сады заселены как прежде", int(buildings.population_before_seasonality.sum())],
        ["Уточнённые атрибуты, постоянное население без садов", int(buildings.population_uncalibrated.sum())],
        ["Калиброванное распределение ориентира 01.01.2025", target],
    ], columns=["Вариант", "Население"])
    scenarios["Отклонение от ориентира, %"] = (scenarios["Население"] / target - 1) * 100
    scenarios.to_csv(data / "population_scenarios.csv", index=False)
    audit_columns = ["osm_key", "building_raw", "levels_raw", "number_of_floors", "floors_source",
        "is_living", "use_source", "revision_note", "zone", "living_area", "seasonal_garden",
        "population_initial", "population_before_seasonality", "population_uncalibrated", "population_model", "geometry"]
    audit = buildings[audit_columns].copy()
    audit["floors_initial"] = audit.osm_key.map(original.number_of_floors)
    audit["living_initial"] = audit.osm_key.map(original.is_living)
    blocks = gpd.read_file(data / "blocks_review.geojson").to_crs(buildings.crs)
    points = audit.copy()
    points["geometry"] = points.geometry.representative_point()
    audit["block_id"] = gpd.sjoin(points, blocks[["block_id", "geometry"]], predicate="within").block_id
    audit.drop(columns="geometry").to_csv(data / "population_building_audit.csv", index=False)
    old_blocks = pd.read_csv(data / "population_initial/blocks_results.csv")
    top_ids = old_blocks.nlargest(10, "population").block_id
    audit[audit.block_id.isin(top_ids)].drop(columns="geometry").to_csv(
        data / "population_top10_blocks_audit.csv", index=False)
    scenarios.to_json(data / "population_scenarios.json", orient="records", force_ascii=False, indent=2)
    return buildings
