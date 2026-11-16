"""HTTP, сохранение и защита последовательности эксперимента без реального автопоиска."""

import copy
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from app import Application, Conflict, create_server
from model import Model


class SyntheticModel:
    """Тестовые числа для проверки согласования А/Б; не результаты Обнинска."""

    ids = list(range(298))
    validate_schools = Model.validate_schools

    def __init__(self, output):
        self.output = output

    def calculate(self, schools):
        return {"schools": copy.deepcopy(schools), "summary": {"capacity_added": sum(s["capacity"] for s in schools)},
                "records": []}

    def write_result(self, name, result):
        (self.output / (name + ".json")).write_text(json.dumps(result))


def test_manual_gate_and_persistence_synthetic(tmp_path):
    model = SyntheticModel(tmp_path)
    app = Application(model)
    with pytest.raises(Conflict):
        app.start_search(600)
    with pytest.raises(Conflict):
        app.approve_manual()
    with pytest.raises(ValueError):
        app.save_scenario({"name": "А", "role": "A", "reason": "", "schools": [{"block_id": 1, "capacity": 600}]})
    a = app.save_scenario({"name": "А (синтетический тест)", "role": "A", "reason": "Тест последовательности",
        "schools": [{"block_id": 1, "capacity": 600}]})
    b = app.save_scenario({"name": "Б (синтетический тест)", "role": "B", "reason": "Два тестовых квартала",
        "schools": [{"block_id": 2, "capacity": 300}, {"block_id": 3, "capacity": 300}]})
    assert not app.state["manual_approved"] and not app.state["search_started"]
    reloaded = Application(model)
    assert reloaded.state["manual"] == {"A": a["id"], "B": b["id"]}
    assert reloaded.approve_manual()["manual_approved"]
    with pytest.raises(Conflict):
        reloaded.save_scenario({"name": "А задним числом", "role": "A", "reason": "Нельзя",
            "schools": [{"block_id": 9, "capacity": 600}]})
    assert not list(tmp_path.glob("auto_*"))


def test_http_real_baseline_plan_csv_and_saved_reload(model):
    app = Application(model)
    server = create_server(app, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def post(path, body):
        request = Request(base + path, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    try:
        with urlopen(base + "/api/bootstrap", timeout=30) as response:
            data = json.load(response)
        assert len(data["blocks"]["features"]) == len(data["baseline"]["records"]) == 298
        assert {f["properties"]["block_id"] for f in data["blocks"]["features"]} == {
            row["block_id"] for row in data["baseline"]["records"]}
        assert post("/api/calculate", {"schools": []}) == model.baseline
        for value in [0, -1, 1.5, "600", True]:
            with pytest.raises(HTTPError) as error:
                post("/api/calculate", {"schools": [{"block_id": 2, "capacity": value}]})
            assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            post("/api/search/start", {"capacity": 600})
        assert error.value.code == 409
        result = post("/api/calculate", {"schools": [{"block_id": 2, "capacity": 17}]})
        entry = post("/api/scenarios", {"name": "Техническая проверка 17 мест", "role": "custom",
            "schools": [{"block_id": 2, "capacity": 17}], "reason": "Не вариант А или Б"})
        assert entry["result"] == result
        assert Application(model).state["scenarios"][0]["id"] == entry["id"]
        assert (model.output / ("scenario_" + entry["id"] + ".csv")).exists()
        assert post("/api/calculate", {"schools": []}) == model.baseline
        with urlopen(base + "/app.js") as response:
            assert b"csvText" in response.read()
        with urlopen(base + "/vendor/leaflet.js") as response:
            assert response.status == 200
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/../examples/data/obninsk/practice3/blocks_results.csv")
        assert error.value.code == 404
        assert model.verify_source_files()
        assert not app.state["search_started"] and not app.state["manual"]
        assert not list(model.output.glob("auto_*"))
    finally:
        server.shutdown()
        server.server_close()
