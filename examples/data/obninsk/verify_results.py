"""Проверить целостность результатов и комплекта для практики № 3."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import shape

DATA = Path(__file__).resolve().parent
approved = json.loads((DATA / "blocks_review.geojson").read_text())["features"]
result = json.loads((DATA / "blocks_results.geojson").read_text())["features"]
approved = {f["properties"]["block_id"]: shape(f["geometry"]) for f in approved}
result = {f["properties"]["block_id"]: f for f in result}
assert set(result) == set(approved) == set(range(298))
for bid, feature in result.items():
    geometry = shape(feature["geometry"])
    assert geometry.is_valid and geometry.equals_exact(approved[bid], tolerance=1e-8)
blocks = pd.read_csv(DATA / "blocks_results.csv", index_col="block_id")
matrix = pd.read_csv(DATA / "travel_time_minutes.csv", index_col="block_id")
matrix.columns = matrix.columns.astype(int)
assert matrix.shape == (298, 298)
assert matrix.index.equals(blocks.index) and matrix.columns.equals(blocks.index)
assert np.isfinite(matrix.to_numpy()).all() and (matrix.to_numpy() >= 0).all()
assert np.allclose(matrix, matrix.T) and np.allclose(np.diag(matrix), 0)
assert (blocks.demand_within + blocks.unmet_demand == blocks.demand).all()
assert blocks.demand_within.sum() <= blocks.capacity.sum()
assert blocks.provision_strong.dropna().between(0, 1).all()
for column in ["mxi", "gsi"]:
    assert blocks[column].dropna().between(0, 1).all()
assert blocks.loc[blocks.demand.eq(0), "provision_strong"].isna().all()
assert blocks.loc[blocks.fsi.eq(0), ["mxi", "l", "osr", "spacematrix", "strelka"]].isna().all().all()
schools = pd.read_csv(DATA / "schools.csv")
assert schools.capacity_baseline.sum() == blocks.capacity.sum()
assert schools.groupby("block_id").capacity_baseline.sum().eq(
    blocks.capacity.reindex(schools.block_id.unique()).sort_index()).all()
organizations = list(csv.DictReader((DATA / "school_organizations.csv").open()))
assert len(organizations) == 24
locked = json.loads((DATA / "population_revision_locked_files.json").read_text())
for filename, digest in locked.items():
    assert hashlib.sha256((DATA / filename).read_bytes()).hexdigest() == digest, filename
initial = pd.read_csv(DATA / "population_initial/blocks_results.csv")
assert initial.population.sum() == 198871
assert blocks.population.sum() == 133000 and blocks.capacity.sum() == 9664
scope = json.loads((DATA / "population_scope_check.json").read_text())
assert scope["osm_polygons_equal"] and scope["territorial_area_scaling"] is False
city = json.loads((DATA / "boundary_nominatim.json").read_text())[0]
municipality = json.loads((DATA / "municipality_nominatim.json").read_text())[0]
assert shape(city["geojson"]).equals(shape(municipality["geojson"]))
audit = pd.read_csv(DATA / "population_building_audit.csv")
assert audit.population_model.sum() == 133000
assert audit.population_initial.sum() == 198871
assert audit.loc[audit.seasonal_garden, "population_model"].sum() == 0
assert audit.loc[audit.seasonal_garden, "population_initial"].sum() == 1087
assert audit.loc[~audit.is_living, "population_model"].sum() == 0
assert audit.loc[audit.osm_key.eq("relation/21910049"), "population_model"].iloc[0] == 0
raw_levels = pd.to_numeric(audit.levels_raw, errors="coerce")
observed = raw_levels.between(1, 60)
assert audit.loc[observed, "number_of_floors"].eq(raw_levels[observed]).all()
assert audit.groupby("block_id").population_model.sum().reindex(blocks.index, fill_value=0).eq(blocks.population).all()
assert pd.read_csv(DATA / "population_top10_blocks_audit.csv").block_id.nunique() == 10
notebook = json.loads((DATA / "obninsk_research.ipynb").read_text())
code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
assert all(c["execution_count"] for c in code_cells)
assert not any(o["output_type"] == "error" for c in code_cells for o in c["outputs"])
html = (DATA / "dashboard.html").read_text()
assert "__PAYLOAD__" not in html and '<html lang="ru">' in html
for field in ["fsi", "gsi", "mxi", "l", "osr", "spacematrix", "strelka", "area_accessibility", "provision_strong"]:
    assert field in blocks and f'"{field}"' in html
manifest = {}
for path in sorted((DATA / "practice3").iterdir()):
    if path.is_file() and (DATA / path.name).exists():
        assert path.read_bytes() == (DATA / path.name).read_bytes(), path.name
        manifest[path.name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
report = {"status": "passed", "blocks": 298, "matrix_shape": [298, 298],
          "executed_code_cells": len(code_cells), "notebook_errors": 0,
          "approved_geometry_preserved": True, "mass_balance": True,
          "locked_geometry_and_matrices_unchanged": True,
          "initial_population_preserved": 198871, "calibrated_population": 133000,
          "population_scope_assumption_documented": True,
          "practice3_files": manifest,
          "browser_check": "Синтаксис и обработчики проверены в V8; графический браузер не запускался"}
(DATA / "validation_final.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != "practice3_files"}, ensure_ascii=False, indent=2))
