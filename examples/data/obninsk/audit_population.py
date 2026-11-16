"""Проверить прежнюю модель населения на сохранённых данных."""

import os
from pathlib import Path

DATA = Path(__file__).resolve().parent
os.environ["MPLCONFIGDIR"] = str(DATA / "cache/matplotlib")
os.environ["NUMBA_CACHE_DIR"] = str(DATA / "cache/numba")

import geopandas as gpd
import pandas as pd

buildings = gpd.read_parquet(DATA / "population_initial/buildings_model.parquet")
blocks = gpd.read_file(DATA / "blocks_review.geojson").to_crs(buildings.crs)
joined = gpd.sjoin(buildings, blocks[["block_id", "geometry"]], predicate="intersects")
joined = joined.sort_index().loc[lambda df: ~df.index.duplicated()]
buildings["block_id"] = joined.block_id
print("Исходное население:", buildings.population.sum())
for column in ["zone", "building_raw", "use_source", "floors_source"]:
    print("\n", column)
    print(buildings.groupby(column).agg(count=("population", "size"), population=("population", "sum"),
          floors=("number_of_floors", "median")).sort_values("population", ascending=False).to_string())
garden = buildings.zone.eq("allotments")
print("\nСады:", garden.sum(), "жилых:", (garden & buildings.is_living).sum(),
      "население:", buildings.loc[garden, "population"].sum())
top = buildings.groupby("block_id").population.sum().nlargest(10)
print("\nСамые населённые кварталы:\n", top.to_string())
columns = ["osm_key", "block_id", "building_raw", "name", "number_of_floors", "levels_raw", "floors_source",
           "use_source", "zone", "footprint_area", "population", "building:flats", "height"]
print("\nКрупнейшие здания в этих кварталах:")
print(buildings[buildings.block_id.isin(top.index)].nlargest(30, "population")[columns].to_string(index=False))
flats = pd.to_numeric(buildings.get("building:flats"), errors="coerce")
sample = buildings[flats.gt(0) & buildings.is_living].copy()
sample["flats"] = flats
sample["gross_per_flat"] = sample.build_floor_area / sample.flats
print("\nКвартирных наблюдений:", len(sample), "квартир:", sample.flats.sum())
print(sample[["gross_per_flat", "number_of_floors"]].describe().to_string())
buildings.drop(columns="geometry").to_csv(DATA / "population_audit_before.csv", index=False)
