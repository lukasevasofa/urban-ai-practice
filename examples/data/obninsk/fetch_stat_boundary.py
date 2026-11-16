"""Получить только малую геометрию округа для проверки статистического охвата."""

import json
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent
target = DATA / "municipality_nominatim.json"
if not target.exists():
    response = requests.get("https://nominatim.openstreetmap.org/lookup",
        params={"osm_ids": "R1192998", "format": "jsonv2", "polygon_geojson": 1},
        headers={"User-Agent": "ObninskUrbanismStudentResearch/1.0"}, timeout=45)
    response.raise_for_status()
    target.write_text(response.text)
result = json.loads(target.read_text())
print([(r["osm_id"], r["display_name"], r["geojson"]["type"]) for r in result])
