"""Создать и выполнить первый этап ноутбука Обнинска на сохранённых данных OSM."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ["MPLCONFIGDIR"] = str(ROOT / "cache" / "matplotlib")
os.environ["NUMBA_CACHE_DIR"] = str(ROOT / "cache" / "numba")
os.environ["IPYTHONDIR"] = str(ROOT / "cache" / "ipython")
os.environ["JUPYTER_RUNTIME_DIR"] = str(ROOT / "cache" / "jupyter")

import nbformat
from nbclient import NotebookClient

cells = [
    nbformat.v4.new_markdown_cell("""# Практическая работа № 2. Обнинск

## Этап 1. Территория и кварталы — для согласования

Данные: OpenStreetMap, административная граница отношения **3396088**.
Граница OSM требует визуального согласования и не заменяет юридическое описание границ города.
Исходные ответы Nominatim и стандартного API OpenStreetMap сохранены рядом с ноутбуком; повторное выполнение не обращается к API.

Методика: [задание](https://mvin8.github.io/ai-technologies-in-urbanism/content/practice/practice-02.html),
[исходный pipeline](https://github.com/aimclub/blocksnet/blob/main/examples/pipeline.ipynb).
Используются готовые функции BlocksNet 1.0.0a9. Площади рассчитаны в UTM 37N, EPSG:32637.
На этом этапе показатели населения, морфологии и обеспеченности ещё **не рассчитаны**.
"""),
    nbformat.v4.new_code_cell('''from pathlib import Path
import json
import os

DATA = Path.cwd()
assert (DATA / "cutting_osm.json").exists(), "Откройте ноутбук из папки examples/data/obninsk"
os.environ["MPLCONFIGDIR"] = str(DATA / "cache" / "matplotlib")
os.environ["NUMBA_CACHE_DIR"] = str(DATA / "cache" / "numba")

import folium
import geopandas as gpd
import osmnx as ox
from shapely.geometry import shape
from blocksnet.blocks.cutting import preprocess_urban_objects, cut_urban_blocks
from blocksnet.blocks.cutting.processing.utils.merge_blocks import merge_invalid_blocks
from blocksnet.enums import BlockCategory

ox.settings.use_cache = False
ox.settings.log_file = False
ox.settings.cache_folder = DATA / "cache" / "osmnx"
ox.settings.logs_folder = DATA / "cache" / "logs"
'''),
    nbformat.v4.new_code_cell('''results = json.loads((DATA / "boundary_nominatim.json").read_text())
city = next(r for r in results if r["osm_id"] == 3396088)
boundary = gpd.GeoDataFrame({"name": ["Обнинск"], "osm_relation": [3396088]},
                            geometry=[shape(city["geojson"])], crs=4326)
boundary.to_file(DATA / "boundary.geojson", driver="GeoJSON")
response = json.loads((DATA / "cutting_osm.json").read_text())
# Вспомогательный конвертер OSMnx 2.1.1: один сохранённый ответ, без новых запросов.
features = ox.features._create_gdf([response], boundary.union_all(),
                                 {"highway": True, "railway": True, "natural": "water",
                                  "waterway": True, "water": True, "landuse": "basin"})
features.to_parquet(DATA / "cutting_features.parquet")
print("Дата OSM:", response.get("osm3s", {}).get("timestamp_osm_base"))
print("Площадь границы, км²:", round(boundary.to_crs(32637).area.sum() / 1e6, 2))
'''),
    nbformat.v4.new_markdown_cell('''### Правила нарезки

Как в pipeline, используются улицы основных классов, жилые улицы и проезды `unclassified`/`living_street`.
Дворовые `service`, тропинки и пешеходные пути не разрезают кварталы; позднее они нужны для пешеходного графа.
Пути действующей железной дороги сохраняются; платформы и заброшенные пути не служат границами.
Водные площади исключаются библиотекой, реки и каналы служат линейными границами.

Для устранения очевидных технических фрагментов объединяем участки менее 0,1 га или условной шириной
`2 × площадь / периметр` менее 6 м с соседом готовой функцией BlocksNet по наибольшей общей границе.
Это прозрачные модельные пороги, а не норматив. Исходные кварталы сохраняются отдельно.
Парки и промышленные территории не удаляем; оставшиеся подозрительные геометрии выделяем на карте.
'''),
    nbformat.v4.new_code_cell('''street_types = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
                "residential", "living_street"]
for column in ["highway", "railway", "natural", "water", "waterway", "landuse"]:
    if column not in features:
        features[column] = None
linear = features.geom_type.isin(["LineString", "MultiLineString"])
roads = features[linear & features["highway"].isin(street_types)].to_crs(32637)
railways = features[linear & features["railway"].isin(["rail", "narrow_gauge", "light_rail"])].to_crs(32637)
water_mask = (features["natural"].eq("water") | features["water"].notna()
              | features["waterway"].isin(["river", "canal", "ditch", "stream"])
              | features["landuse"].eq("basin"))
water = features[water_mask & features.geom_type.isin(
    ["Polygon", "MultiPolygon", "LineString", "MultiLineString"])].to_crs(32637)
roads, railways, water = [g[["geometry"]].reset_index(drop=True) for g in [roads, railways, water]]
lines, polygons = preprocess_urban_objects(roads, railways, water)
raw = cut_urban_blocks(boundary.to_crs(32637), lines, polygons)
raw.to_crs(4326).to_file(DATA / "blocks_raw.geojson", driver="GeoJSON")
raw["category"] = BlockCategory.NORMAL
small = (raw.area < 1000) | (2 * raw.area / raw.length < 6)
raw.loc[small, "category"] = BlockCategory.INVALID
blocks = merge_invalid_blocks(raw).drop(columns="category")
blocks["block_id"] = range(len(blocks))
blocks["area_ha"] = blocks.area / 10000
blocks["width_proxy_m"] = 2 * blocks.area / blocks.length
blocks["review"] = (blocks.area < 1000) | (blocks["width_proxy_m"] < 6)
assert blocks.geometry.is_valid.all() and blocks["block_id"].is_unique
assert blocks.area.min() > 0
overlap = (blocks.area.sum() - blocks.union_all().area)
assert overlap < 1, f"Перекрытие кварталов: {overlap} м²"
blocks.to_crs(4326).to_file(DATA / "blocks_review.geojson", driver="GeoJSON")
blocks.drop(columns="geometry").to_csv(DATA / "blocks_review.csv", index=False)
print(f"Улицы: {len(roads)}; ж/д: {len(railways)}; водные объекты: {len(water)}")
print(f"Кварталы: {len(raw)} исходных → {len(blocks)} после объединения фрагментов")
print(f"Осталось фрагментов для просмотра: {blocks.review.sum()}")
print(f"Суммарная площадь кварталов: {blocks.area.sum() / 1e6:.2f} км²")
display(blocks[["area_ha", "width_proxy_m"]].describe().round(2))
'''),
    nbformat.v4.new_code_cell('''m = folium.Map(tiles="OpenStreetMap", control_scale=True)
folium.GeoJson(boundary, name="Граница Обнинска", style_function=lambda f:
               {"color": "#c02626", "weight": 3, "fillOpacity": 0}).add_to(m)
folium.GeoJson(blocks.to_crs(4326), name="Кварталы для согласования",
    style_function=lambda f: {"color": "#334155", "weight": 1,
        "fillColor": "#ef4444" if f["properties"]["review"] else "#38bdf8", "fillOpacity": 0.3},
    highlight_function=lambda f: {"weight": 3, "fillOpacity": 0.6},
    tooltip=folium.GeoJsonTooltip(fields=["block_id", "area_ha", "width_proxy_m", "review"],
        aliases=["ID квартала", "Площадь, га", "Условная ширина, м", "Требует просмотра"])) .add_to(m)
folium.GeoJson(raw[["geometry"]].to_crs(4326), name="Исходная нарезка", show=False,
               style_function=lambda f: {"color": "#a855f7", "weight": 1, "fillOpacity": 0}).add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
b = boundary.total_bounds
m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
m.get_root().html.add_child(folium.Element(
    '<div style="position:fixed;bottom:25px;left:15px;z-index:9999;background:white;padding:12px;'
    'border:1px solid #888;font:14px Arial;max-width:320px">'
    '<b>Обнинск · согласование кварталов</b><br>Красная линия — граница города.<br>'
    'Голубые участки — кварталы; красные — мелкие/узкие фрагменты для просмотра.<br>'
    'Наведите курсор на квартал. Крупные парки и промзоны сохранены.</div>'))
m.save(DATA / "boundary_blocks_review.html")
m
'''),
    nbformat.v4.new_markdown_cell('''## Остановка для согласования

Проверьте границу и внешний вид кварталов на карте. После согласования продолжим:
функциональные зоны → здания и восстановление атрибутов → население → школы → морфология →
пешеходный граф и матрица минут → конкурентная обеспеченность и area_accessibility → экспорт → дашборд.

ID кварталов пока предварительные: после согласования геометрии они будут закреплены для матрицы и практики № 3.
Готовый граф ещё не выбран; его поиск и проверка выполняются после согласования территории.
Это промежуточный этап, а не завершённая практическая работа.
'''),
]
nb = nbformat.v4.new_notebook(cells=cells, metadata={"kernelspec": {
    "display_name": "Python 3.12 (.venv)", "language": "python", "name": "python3"}})
path = ROOT / "obninsk_research.ipynb"
nbformat.write(nb, path)
NotebookClient(nb, timeout=240, resources={"metadata": {"path": str(ROOT)}}).execute()
nbformat.write(nb, path)
print(path)
for cell in nb.cells:
    for output in cell.get("outputs", []):
        if output.output_type == "stream":
            print(output.text)
