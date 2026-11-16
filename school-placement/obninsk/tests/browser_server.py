"""Изолированный сервер для WebKit-проверки; не сохраняет выбор в рабочие сценарии пользователя."""

import sys
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from app import Application, create_server
from model import Model

directory = APP / "runtime" / ("browser-test-" + uuid.uuid4().hex[:8])
application = Application(Model(output=directory))
server = create_server(application, 8766)
print(f"WebKit test server: http://127.0.0.1:8766; output={directory}", flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
