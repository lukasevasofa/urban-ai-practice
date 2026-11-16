"""Объединить четыре сохранённых XML-фрагмента OSM для конвертера OSMnx."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

DATA = Path(__file__).resolve().parent
elements = {}
timestamps = []
for path in sorted(DATA.glob("osm_map_*.osm")):
    root = ET.parse(path).getroot()
    for item in root:
        if item.tag == "meta":
            timestamps.append(item.attrib.get("osm_base", ""))
        if item.tag not in ("node", "way", "relation"):
            continue
        element = {"type": item.tag, "id": int(item.attrib["id"])}
        if item.tag == "node":
            element.update(lat=float(item.attrib["lat"]), lon=float(item.attrib["lon"]))
        elif item.tag == "way":
            element["nodes"] = [int(nd.attrib["ref"]) for nd in item.findall("nd")]
        else:
            element["members"] = [dict(type=m.attrib["type"], ref=int(m.attrib["ref"]),
                                       role=m.attrib.get("role", "")) for m in item.findall("member")]
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in item.findall("tag")}
        if tags:
            element["tags"] = tags
        elements[(item.tag, element["id"])] = element
assert elements, "Нет сохранённых XML-фрагментов"
content = {"elements": list(elements.values()), "osm3s": {"timestamp_osm_base": timestamps}}
(DATA / "cutting_osm.json").write_text(json.dumps(content, ensure_ascii=False))
(DATA / "osm_source.json").write_text(json.dumps({
    "source": "https://api.openstreetmap.org/api/0.6/map",
    "files": [p.name for p in sorted(DATA.glob("osm_map_*.osm"))],
    "boundary": "https://www.openstreetmap.org/relation/3396088",
    "timestamp_osm_base": timestamps,
    "note": "Четыре четверти bounding box границы; дубликаты удалены по типу и OSM ID.",
}, ensure_ascii=False, indent=2))
print(f"Объектов после удаления дубликатов: {len(elements)}")
