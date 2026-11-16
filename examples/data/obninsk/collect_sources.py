"""Сохранить компактные открытые источники для проверки школ и населения."""

from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "sources"
DATA.mkdir(exist_ok=True)
sources = {
    "population.html": "https://obninsk.ru/obninsk/economic-development/stat/",
    "school_register.html": "https://www.obninsk.ru/obninsk/social-sphere/education/Obninskschools/",
    "school_1144.html": "https://obninsk.ru/obninsk/economic-development/partnership/",
    "school_1000.html": "https://www.admobninsk.ru/news/news_24274.html",
    "municipal_area.html": "https://base.garant.ru/412329080/b89690251be5277812a78962f6302560/",
    "graph_repository.json": "https://api.github.com/repos/IDUclub/IduEdu/contents",
    "graph_releases.json": "https://api.github.com/repos/IDUclub/IduEdu/releases?per_page=3",
}
for name, url in sources.items():
    path = DATA / name
    if path.exists():
        continue
    try:
        result = requests.get(url, timeout=45)
        result.raise_for_status()
        path.write_bytes(result.content)
        print(name, len(result.content), flush=True)
    except requests.RequestException as error:
        print(name, str(error), flush=True)
