"""Локальное приложение Обнинска. Запуск: .venv/bin/python school-placement/obninsk/app.py."""

import argparse
import json
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from model import APP_DIR, Model, enumerate_candidates, positive_integer


class Conflict(ValueError):
    """Действие пока недоступно по последовательности эксперимента."""


class Application:
    """Расчёт, сохранённые сценарии и один фоновый последовательный перебор."""

    def __init__(self, model: Model):
        self.model = model
        self.lock = threading.RLock()
        self.solver_lock = threading.Lock()
        self.cancel = threading.Event()
        self.state_path = model.output / "scenarios.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            "scenarios": [], "manual": {}, "manual_approved": False, "search_started": False}
        self.search = {"status": "not_started", "checked": 0, "total": len(model.ids), "rows": [],
                       "best_blocks": [], "errors": 0, "complete": False}
        self.search_file = None
        if self.state.get("latest_search"):
            self.search_file = self.model.output / self.state["latest_search"]
            self.search = json.loads(self.search_file.read_text())
            if self.search["status"] == "running":
                self.search.update(status="interrupted", complete=False, best_blocks=[],
                                   error="Сервер был остановлен до завершения перебора.")
                self._save_search()

    def persist(self) -> None:
        """Сохранить сценарии в папке приложения, не затрагивая исходные данные."""
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2, allow_nan=False))

    def calculate(self, schools: list[dict]) -> dict:
        with self.solver_lock:
            return self.model.calculate(schools)

    def bootstrap(self) -> dict:
        return {"blocks": {"type": "FeatureCollection", "features": [
                    {"type": "Feature", "geometry": f["geometry"],
                     "properties": {"block_id": f["properties"]["block_id"]}}
                    for f in self.model.geometry["features"]]},
                "points": self.model.points, "existing_schools": self.model.schools,
                "baseline": self.model.baseline, "parameters": self.model.params,
                "state": self.get_state(), "baseline_check": self.model.baseline_check}

    def get_state(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state))

    def save_scenario(self, body: dict) -> dict:
        name, reason = str(body.get("name", "")).strip(), str(body.get("reason", "")).strip()
        role = body.get("role", "custom")
        if not name or len(name) > 120:
            raise ValueError("Введите название сценария до 120 символов.")
        if role not in ("A", "B", "V", "custom"):
            raise ValueError("Неизвестный тип сценария.")
        plan = self.model.validate_schools(body.get("schools"))
        if not plan:
            raise ValueError("Добавьте хотя бы одну школу; исходное состояние уже сохранено отдельно.")
        if role in ("A", "B"):
            with self.lock:
                if self.state["manual_approved"] or self.state["search_started"]:
                    raise Conflict("Ручные варианты зафиксированы. Новый вариант можно сохранить как дополнительный.")
            if not reason or len(reason) > 3000:
                raise ValueError("Для А и Б запишите обоснование выбора до автоматического поиска.")
            expected = [600] if role == "A" else [300, 300]
            if sorted(s["capacity"] for s in plan) != expected:
                raise ValueError("Для А нужна одна школа на 600 мест, для Б — две по 300 в разных кварталах.")
        if role == "V":
            with self.lock:
                if not (self.search["complete"] and self.search.get("capacity") == 600 and len(plan) == 1
                        and plan[0]["capacity"] == 600 and plan[0]["block_id"] in self.search["best_blocks"]):
                    raise Conflict("Вариант В сохраняется только после полного поиска школы на 600 мест в лучшем квартале.")
        result = self.calculate(plan)
        entry = {"id": uuid.uuid4().hex[:12], "name": name, "role": role, "reason": reason,
                 "saved_at": datetime.now(timezone.utc).isoformat(), "result": result}
        with self.lock:
            # Повторная проверка защищает от фиксации ручного варианта после согласования в другом окне.
            if role in ("A", "B") and (self.state["manual_approved"] or self.state["search_started"]):
                raise Conflict("Ручные варианты уже зафиксированы.")
            self.state["scenarios"].append(entry)
            if role in ("A", "B"):
                self.state["manual"][role] = entry["id"]
            self.model.write_result("scenario_" + entry["id"], result)
            self.persist()
        return entry

    def approve_manual(self) -> dict:
        with self.lock:
            if set(self.state["manual"]) != {"A", "B"}:
                raise Conflict("Сначала сохраните и обоснуйте ручные сценарии А и Б.")
            self.state["manual_approved"] = True
            self.state["approved_at"] = datetime.now(timezone.utc).isoformat()
            self.persist()
            return self.get_state()

    def start_search(self, capacity: object) -> dict:
        positive_integer(capacity)
        with self.lock:
            if not self.state["manual_approved"]:
                raise Conflict("Автопоиск заблокирован до сохранения и подтверждения ручных вариантов А и Б.")
            if self.search["status"] == "running":
                raise Conflict("Перебор уже идёт. Дождитесь завершения или остановите его.")
            self.cancel.clear()
            self.state["search_started"] = True
            self.persist()
            self.search = {"status": "running", "capacity": capacity, "checked": 0, "total": len(self.model.ids),
                           "rows": [], "best_blocks": [], "errors": 0, "complete": False}
            self.search_file = self.model.output / f"auto_{uuid.uuid4().hex[:12]}.json"
            self.state["latest_search"] = self.search_file.name
            self.persist()
            self._save_search()
            threading.Thread(target=self._search_worker, args=(capacity,), daemon=True).start()
            return self.get_search()

    def _save_search(self) -> None:
        if self.search_file:
            self.search_file.write_text(json.dumps(self.search, ensure_ascii=False, indent=2, allow_nan=False))

    def _search_worker(self, capacity: int) -> None:
        def progress(rows: list[dict], checked: int) -> None:
            with self.lock:
                self.search.update(rows=rows, checked=checked,
                                   errors=sum(row.get("error") is not None for row in rows))
                self._save_search()

        try:
            result = enumerate_candidates(self.model.ids, capacity, self.calculate, progress, self.cancel.is_set)
            with self.lock:
                status = "complete" if result["complete"] else "cancelled" if self.cancel.is_set() else "partial"
                self.search.update(result, status=status)
                self._save_search()
        except Exception as error:
            with self.lock:
                self.search.update(status="failed", complete=False, best_blocks=[], error=str(error))
                self._save_search()

    def get_search(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.search))


class Handler(BaseHTTPRequestHandler):
    """Минимальный HTTP API и только явно перечисленные статические файлы."""

    def log_message(self, *_args) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        app = self.server.application
        if path == "/api/bootstrap":
            self.send_json(app.bootstrap())
        elif path == "/api/search":
            self.send_json(app.get_search())
        else:
            static = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css"),
                      "/vendor/leaflet.js": ("vendor/leaflet.js", "text/javascript"),
                      "/vendor/leaflet.css": ("vendor/leaflet.css", "text/css")}
            if path not in static:
                self.send_json({"error": "Страница не найдена."}, 404)
                return
            filename, content_type = static[path]
            data = (APP_DIR / "static" / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def do_POST(self) -> None:
        try:
            # Чужой сайт не должен запускать локальные расчёты через браузер пользователя.
            if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                self.send_json({"error": "Запрос должен идти из локального приложения."}, 403)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 100_000:
                raise ValueError("Слишком большой запрос.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Ожидается объект параметров.")
            app = self.server.application
            path = urlsplit(self.path).path
            if path == "/api/calculate":
                result = app.calculate(body.get("schools"))
                app.model.write_result("latest", result)
                self.send_json(result)
            elif path == "/api/scenarios":
                self.send_json(app.save_scenario(body))
            elif path == "/api/approve-manual":
                self.send_json(app.approve_manual())
            elif path == "/api/search/start":
                self.send_json(app.start_search(body.get("capacity", 600)))
            elif path == "/api/search/cancel":
                app.cancel.set()
                self.send_json(app.get_search())
            else:
                self.send_json({"error": "Команда не найдена."}, 404)
        except Conflict as error:
            self.send_json({"error": str(error)}, 409)
        except (ValueError, TypeError, KeyError) as error:
            self.send_json({"error": str(error)}, 400)
        except Exception as error:
            self.send_json({"error": f"Расчёт не завершён: {error}"}, 500)


def create_server(application: Application, port: int = 8765) -> ThreadingHTTPServer:
    """Открыть сервер только на 127.0.0.1; port=0 допустим для проверки."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.application = application
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Обнинск: локальное моделирование размещения школ")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    application = Application(Model())
    server = create_server(application, args.port)
    print(f"Исходный расчёт совпал: 133000 жителей, 9664 места, 57,46%, дефицит 6812.", flush=True)
    print(f"Откройте http://127.0.0.1:{server.server_port} — остановка Ctrl+C.", flush=True)
    print("Автоматический поиск не запускался и заблокирован до подтверждения А и Б.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        application.cancel.set()
    finally:
        server.server_close()
