"""Сохранить небольшие файлы Leaflet для локального запуска интерфейса."""

from pathlib import Path
import requests

directory = Path(__file__).resolve().parent / "static/vendor"
for filename in ["leaflet.js", "leaflet.css"]:
    target = directory / filename
    if not target.exists():
        response = requests.get(f"https://unpkg.com/leaflet@1.9.4/dist/{filename}", timeout=40)
        response.raise_for_status()
        target.write_bytes(response.content)
    print(filename, target.stat().st_size)
