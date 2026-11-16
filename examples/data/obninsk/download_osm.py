"""Однократная загрузка границы и объектов для согласования кварталов."""

import json
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "ObninskUrbanismStudentResearch/1.0"}

boundary_path = DATA / "boundary_nominatim.json"
if not boundary_path.exists():
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": "Обнинск, Калужская область, Россия", "format": "jsonv2",
                "polygon_geojson": 1, "addressdetails": 1, "limit": 5},
        headers=HEADERS, timeout=60,
    )
    response.raise_for_status()
    boundary_path.write_text(response.text)

results = json.loads(boundary_path.read_text())
city = next(r for r in results if r["osm_id"] == 3396088)
south, north, west, east = map(float, city["boundingbox"])
mid_x, mid_y = (west + east) / 2, (south + north) / 2
boxes = [(west, south, mid_x, mid_y), (mid_x, south, east, mid_y),
         (west, mid_y, mid_x, north), (mid_x, mid_y, east, north)]
# Overpass оказался недоступен: используем стандартный API и четыре малых XML-фрагмента.
for number, bbox in enumerate(boxes):
    target = DATA / f"osm_map_{number}.osm"
    if target.exists():
        print("Используем сохранённый файл:", target.name)
        continue
    response = requests.get("https://api.openstreetmap.org/api/0.6/map",
                            params={"bbox": ",".join(map(str, bbox))}, headers=HEADERS, timeout=120)
    response.raise_for_status()
    target.write_bytes(response.content)
    print(target.name, len(response.content))
