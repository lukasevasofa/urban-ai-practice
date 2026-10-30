"""Лёгкие проверки проекта без импорта BlocksNet и выполнения ноутбуков."""

import argparse
import ast
import csv
import json
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "examples/data/korenovsk/results"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def invalid(value):
        raise ValueError(f"{path}: недопустимое JSON-значение {value}")

    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid)


def check_sources():
    paths = list(ROOT.glob("*.py"))
    for directory in ("my_package", "tests", "scripts", "docs/source"):
        paths.extend((ROOT / directory).rglob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    notebooks = list((ROOT / "examples").glob("*.ipynb"))
    require(notebooks, "Не найдены учебные ноутбуки")
    cells_count = 0
    for path in notebooks:
        notebook = read_json(path)
        require(notebook.get("nbformat") == 4, f"{path}: ожидается формат Jupyter 4")
        require(isinstance(notebook.get("cells"), list), f"{path}: отсутствует список cells")
        for index, cell in enumerate(notebook["cells"]):
            require(cell.get("cell_type") in {"code", "markdown", "raw"}, f"{path}: неизвестный тип ячейки")
            source = cell.get("source")
            require(isinstance(source, (str, list)), f"{path}: отсутствует source ячейки {index}")
            if cell["cell_type"] == "code":
                ast.parse("".join(source), filename=f"{path}:cell-{index}")
                require(isinstance(cell.get("outputs"), list), f"{path}: outputs должен быть списком")
                cells_count += 1
    print(f"Синтаксис: {len(paths)} Python-файлов, {len(notebooks)} ноутбука, {cells_count} ячеек без выполнения")


def check_structure():
    for name in ("README.rst", "LICENSE", "pyproject.toml", "build_dashboard.py", "dashboard.html",
                 "examples/korenovsk_research.ipynb", "examples/korenovsk_geometry_diagnostics.ipynb",
                 "examples/data/korenovsk/processed/blocks.geojson"):
        require((ROOT / name).is_file(), f"Отсутствует обязательный файл: {name}")
    report = read_json(RESULTS / "quality_report.json")
    geojson = read_json(RESULTS / "blocks_indicators.geojson")
    require(geojson.get("type") == "FeatureCollection", "Итоговые кварталы должны быть FeatureCollection")
    features = geojson.get("features")
    require(isinstance(features, list) and features, "Итоговый GeoJSON пуст")
    ids = [f["properties"]["block_id"] for f in features]
    require(len(ids) == len(set(ids)), "В GeoJSON повторяются block_id")
    require(report.get("blocks") == len(ids), "Отчёт качества и GeoJSON содержат разное число кварталов")
    require(report.get("population_is_official") is False, "Население должно быть помечено как модельное")
    require(report.get("network_calculated") is False, "Проверки рассчитаны на текущий этап без графа")
    require(report.get("versions", {}).get("blocksnet") == "1.0.0a9", "Ожидается BlocksNet 1.0.0a9")
    with (RESULTS / "blocks_indicators.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    csv_ids = [int(row["block_id"]) for row in rows]
    require(len(csv_ids) == len(set(csv_ids)) and set(csv_ids) == set(ids), "CSV и GeoJSON не согласованы")
    columns = {"fsi", "gsi", "mxi", "l", "osr", "land_use", "population_density_per_ha",
               "spacematrix_morphotype", "strelka_morphotype", "schools_count", "capacity"}
    for feature in features:
        require(columns <= feature["properties"].keys(), "В квартале отсутствуют поля показателей")
        require(feature.get("geometry", {}).get("type") in {"Polygon", "MultiPolygon"},
                "Квартал должен иметь полигональную геометрию")
    print(f"Структура и сохранённые результаты: {len(ids)} кварталов; CSV, GeoJSON и отчёт согласованы")
    return len(ids)


class DashboardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.in_payload = False
        self.payload = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "script" and attrs.get("id") == "dashboardData":
            self.in_payload = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_payload = False

    def handle_data(self, data):
        if self.in_payload:
            self.payload.append(data)


def check_dashboard(output, expected_count):
    # Генератор только читает готовые результаты. Выход не перезаписывает dashboard.html проекта.
    require(output.resolve() != (ROOT / "dashboard.html").resolve(), "Не перезаписывайте исходный dashboard.html")
    subprocess.run([sys.executable, str(ROOT / "build_dashboard.py"), "--output", str(output)],
                   cwd=ROOT, check=True)
    html = output.read_text(encoding="utf-8")
    parser = DashboardParser()
    parser.feed(html)
    require({"map", "metric", "metricsTable", "qualityFacts", "dashboardData"} <= parser.ids,
            "В HTML отсутствуют обязательные элементы интерфейса")
    payload = json.loads("".join(parser.payload))
    require(len(payload["geojson"]["features"]) == expected_count, "HTML потерял кварталы")
    require(payload["report"]["network_calculated"] is False, "В HTML неверный статус транспортных расчётов")
    for text in ("Время в пути — недоступно", "Обеспеченность школами — недоступна", "area_accessibility — недоступен"):
        require(text in html, f"В HTML отсутствует пояснение: {text}")
    require("__DASHBOARD_DATA__" not in html, "Шаблон HTML не заполнен")
    print("Генерация HTML: карта, таблица, данные и отметки недоступности присутствуют")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", action="store_true", help="Проверить генератор во временной папке")
    parser.add_argument("--dashboard-output", type=Path, help="Сохранить проверенный HTML для артефакта CI")
    args = parser.parse_args()
    check_sources()
    count = check_structure()
    if args.dashboard_output:
        check_dashboard(args.dashboard_output.resolve(), count)
    elif args.dashboard:
        with tempfile.TemporaryDirectory(prefix="korenovsk-ci-") as folder:
            check_dashboard(Path(folder) / "dashboard.html", count)


if __name__ == "__main__":
    main()
