"""Диагностика уже сохранённой выгрузки, без сетевых запросов."""

import json
import os
from pathlib import Path

DATA = Path(__file__).resolve().parent
os.environ["MPLCONFIGDIR"] = str(DATA / "cache/matplotlib")
os.environ["NUMBA_CACHE_DIR"] = str(DATA / "cache/numba")

import geopandas as gpd
import osmnx as ox

ox.settings.use_cache = False
response = json.loads((DATA / "cutting_osm.json").read_text())
boundary = gpd.read_file(DATA / "boundary.geojson")
features = ox.features._create_gdf([response], boundary.union_all(),
                                 {"building": True, "landuse": True, "amenity": "school"})
features.to_parquet(DATA / "research_features.parquet")
buildings = features[features.get("building").notna() & features.geom_type.isin(["Polygon", "MultiPolygon"])]
print("Здания:", len(buildings))
print(buildings.building.value_counts().to_string())
for column in ["building:levels", "height", "building:use", "capacity", "name"]:
    print(column, buildings[column].notna().sum() if column in buildings else 0)
schools = features[features.amenity.eq("school")].reset_index()
columns = [c for c in ["element", "id", "name", "building", "capacity", "addr:street",
                       "addr:housenumber", "operator", "website"] if c in schools]
print(schools[columns].to_string(index=False))
schools[columns].to_csv(DATA / "schools_osm_audit.csv", index=False)
print("Зоны:", features.landuse.value_counts().to_string())
