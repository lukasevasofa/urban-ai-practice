"""Расчёт сценариев на неизменных данных практики №2."""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

APP_DIR = Path(__file__).resolve().parent
SOURCE = APP_DIR.parents[1] / "examples/data/obninsk/practice3"
RUNTIME = APP_DIR / "runtime"
for name, folder in {"MPLCONFIGDIR": "matplotlib", "NUMBA_CACHE_DIR": "numba", "TMPDIR": "tmp"}.items():
    directory = RUNTIME / folder
    directory.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(directory)
tempfile.tempdir = str(RUNTIME / "tmp")
sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
from loguru import logger
from shapely.geometry import shape

# Необязательный torch в BlocksNet выдаёт предупреждение NumPy; расчёт обеспеченности его не использует.
with contextlib.redirect_stderr(io.StringIO()) as import_log:
    from blocksnet.analysis.provision import competitive_provision
if import_log.getvalue():
    (RUNTIME / "import.log").write_text(import_log.getvalue())
logger.disable("blocksnet")


def positive_integer(value: object, title: str = "Вместимость") -> int:
    """Проверить положительное целое число без преобразования дробей и логических значений."""
    if type(value) is not int or value <= 0:
        raise ValueError(f"{title}: требуется положительное целое число.")
    return value


def ranked_candidates(rows: list[dict], expected: int) -> tuple[list[dict], list[int]]:
    """Упорядочить варианты и назвать все лучшие только при полном успешном переборе."""
    ordered = sorted(rows, key=lambda row: (row.get("error") is not None,
        -row.get("reduction", -float("inf")), row["block_id"]))
    complete = len(rows) == expected and all(row.get("error") is None for row in rows)
    best = [row["block_id"] for row in ordered if row["reduction"] == ordered[0]["reduction"]] if complete else []
    return ordered, best


def enumerate_candidates(
    block_ids: list[int], capacity: int, calculate: Callable, progress: Callable, cancelled: Callable = lambda: False,
) -> dict:
    """Проверить каждый квартал независимо, включая варианты с ошибками и равными результатами."""
    positive_integer(capacity)
    rows = []
    for block_id in block_ids:
        if cancelled():
            break
        try:
            summary = calculate([{"block_id": block_id, "capacity": capacity}])["summary"]
            row = {"block_id": block_id, "capacity_added": capacity, "error": None, **summary}
        except Exception as error:  # Ошибка одного варианта не скрывает остальные и не завершает перебор.
            row = {"block_id": block_id, "capacity_added": capacity, "error": str(error) or type(error).__name__}
        rows.append(row)
        ordered, _ = ranked_candidates(rows, len(block_ids))
        progress(ordered, len(rows))
    ordered, best = ranked_candidates(rows, len(block_ids))
    complete = len(rows) == len(block_ids) and all(row.get("error") is None for row in rows)
    return {"rows": ordered, "checked": len(rows), "total": len(block_ids), "complete": complete,
            "best_blocks": best, "errors": sum(row.get("error") is not None for row in rows)}


class Model:
    """Небольшая модель: чтение данных, одна функция сценария и проверка исходного расчёта."""

    def __init__(self, source: Path = SOURCE, output: Path = APP_DIR / "results"):
        self.source, self.output = source, output
        output.mkdir(parents=True, exist_ok=True)
        self.source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in source.iterdir() if path.is_file()}
        self.blocks = pd.read_csv(source / "blocks_results.csv", index_col="block_id").sort_index()
        self.ids = [int(value) for value in self.blocks.index]
        self.matrix = pd.read_csv(source / "travel_time_minutes.csv", index_col=0)
        self.matrix.index = self.matrix.index.astype(int)
        self.matrix.columns = self.matrix.columns.astype(int)
        self.params = json.loads((source / "school_parameters.json").read_text())
        self.geometry = json.loads((source / "blocks_results.geojson").read_text())
        self.schools = json.loads((source / "schools.geojson").read_text())
        assert self.ids == list(range(298)), "Нужны 298 согласованных кварталов с ID 0…297."
        assert self.matrix.index.equals(self.blocks.index) and self.matrix.columns.equals(self.blocks.index)
        assert self.matrix.shape == (298, 298) and np.isfinite(self.matrix.to_numpy()).all()
        assert sorted(feature["properties"]["block_id"] for feature in self.geometry["features"]) == self.ids
        assert self.blocks.population.sum() == 133000 and self.blocks.capacity.sum() == 9664
        self.points = {feature["properties"]["block_id"]: list(shape(feature["geometry"]).representative_point().coords)[0]
                       for feature in self.geometry["features"]}
        self.baseline_frame, _ = self._provision([])
        saved = pd.read_csv(source / "baseline_provision.csv", index_col="block_id")
        assert saved.index.equals(self.blocks.index)
        for column in saved:
            np.testing.assert_allclose(self.baseline_frame[column], saved[column], equal_nan=True, atol=1e-9)
        self.baseline = self.calculate([])
        assert self.baseline["summary"]["unmet"] == 6812
        assert round(self.baseline["summary"]["provision_percent"], 2) == 57.46
        self.write_result("baseline", self.baseline)
        self.baseline_check = {"population": 133000, "capacity": 9664, "unmet": 6812,
            "provision_percent": 57.46, "all_saved_columns_match": True, "source_files": self.source_hashes}
        (output / "baseline_check.json").write_text(json.dumps(self.baseline_check, ensure_ascii=False, indent=2))

    def validate_schools(self, schools: object) -> list[dict]:
        """Проверить кварталы и мощности; одна запись школы на квартал."""
        if not isinstance(schools, list) or len(schools) > 298:
            raise ValueError("План должен содержать список школ не более чем в 298 кварталах.")
        result, seen = [], set()
        for school in schools:
            if not isinstance(school, dict):
                raise ValueError("Некорректная запись новой школы.")
            bid = school.get("block_id")
            if type(bid) is not int or bid not in self.ids:
                raise ValueError("Выберите существующий квартал с ID от 0 до 297.")
            if bid in seen:
                raise ValueError(f"Квартал {bid} уже есть в плане: отредактируйте его вместимость.")
            seen.add(bid)
            result.append({"block_id": bid, "capacity": positive_integer(school.get("capacity"))})
        return result

    def _provision(self, schools: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
        frame = self.blocks[["population", "capacity"]].copy(deep=True)
        for school in schools:
            frame.loc[school["block_id"], "capacity"] += school["capacity"]
        return competitive_provision(frame, self.matrix,
            accessibility=self.params["accessibility_minutes"], demand=self.params["demand_per_1000"],
            self_supply=self.params["self_supply"], max_depth=self.params["max_depth"])

    def calculate(self, schools: object) -> dict:
        """Пересчитать всю территорию, увеличивая только мощности выбранных кварталов."""
        plan = self.validate_schools(schools)
        frame, _ = self._provision(plan)
        baseline = self.baseline_frame
        added = sum(school["capacity"] for school in plan)
        assert frame.capacity.sum() == self.blocks.capacity.sum() + added
        assert frame.demand.equals(baseline.demand)
        assert (frame.demand_left + frame.demand_within == frame.demand).all()
        assert frame.demand_within.sum() <= frame.capacity.sum()
        assert frame.provision_strong.dropna().between(0, 1).all()
        improvement = frame.provision_strong.fillna(0) - baseline.provision_strong.fillna(0)
        summary = {"population": int(self.blocks.population.sum()), "demand": int(frame.demand.sum()),
            "school_count": len(plan), "capacity_added": added, "capacity": int(frame.capacity.sum()),
            "served": int(frame.demand_within.sum()), "unmet": int(frame.demand_left.sum()),
            "provision_percent": float(frame.demand_within.sum() / frame.demand.sum() * 100),
            "reduction": int(baseline.demand_left.sum() - frame.demand_left.sum()),
            "improved_blocks": int((improvement > 1e-9).sum()),
            "worsened_blocks": int((improvement < -1e-9).sum())}
        rows = pd.DataFrame({"population": self.blocks.population,
            "capacity_initial": baseline.capacity, "capacity": frame.capacity,
            "added_capacity": frame.capacity - baseline.capacity, "demand": frame.demand,
            "served_initial": baseline.demand_within, "served": frame.demand_within,
            "provision_initial": baseline.provision_strong, "provision": frame.provision_strong,
            "unmet_initial": baseline.demand_left, "unmet": frame.demand_left,
            "delta_provision_pp": improvement.where(frame.demand.gt(0)) * 100,
            "reduction": baseline.demand_left - frame.demand_left})
        rows.index.name = "block_id"
        return {"schools": plan, "summary": summary,
                "records": json.loads(rows.reset_index().to_json(orient="records", double_precision=12))}

    def write_result(self, name: str, result: dict) -> None:
        """Сохранить расчёт и таблицу только в выходной папке приложения."""
        assert name.replace("_", "").replace("-", "").isalnum()
        (self.output / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        pd.DataFrame(result["records"]).to_csv(self.output / f"{name}.csv", index=False, encoding="utf-8-sig")

    def verify_source_files(self) -> bool:
        """Проверить побайтную неизменность всех входных файлов практики №2."""
        return all(hashlib.sha256((self.source / name).read_bytes()).hexdigest() == digest
                   for name, digest in self.source_hashes.items())
