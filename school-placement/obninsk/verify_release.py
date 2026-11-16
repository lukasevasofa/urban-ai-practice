"""Сохранить итог проверки приложения без запуска оптимизации."""

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

APP = Path(__file__).resolve().parent
SOURCE = APP.parents[1] / "examples/data/obninsk/practice3"
output = APP / "results"
manifest = json.loads((output / "input_manifest.json").read_text())
assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest for name, digest in manifest.items())
baseline = json.loads((output / "baseline.json").read_text())
assert baseline["summary"]["population"] == 133000
assert baseline["summary"]["capacity"] == 9664
assert baseline["summary"]["unmet"] == 6812
assert round(baseline["summary"]["provision_percent"], 2) == 57.46
assert json.loads((output / "baseline_check.json").read_text())["all_saved_columns_match"]
assert len(baseline["records"]) == 298
root = ElementTree.parse(output / "python_tests.xml").getroot()
suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
counts = {name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
          for name in ["tests", "failures", "errors", "skipped"]}
assert counts["tests"] >= 19 and counts["failures"] == counts["errors"] == counts["skipped"] == 0
browser = json.loads((output / "browser_check.json").read_text())
assert browser["status"] == "passed" and browser["auto_search_started"] is False
state_file = output / "scenarios.json"
state = json.loads(state_file.read_text()) if state_file.exists() else {
    "manual": {}, "manual_approved": False, "search_started": False}
assert not state["search_started"] and not list(output.glob("auto_*.json"))
report = {"status": "ready_for_manual_choices", "source_files_unchanged": True,
    "source_file_count": len(manifest), "baseline_matches_all_saved_values": True,
    "python_tests": counts, "webkit_checks_passed": len(browser["checks"]),
    "browser_engine": browser["engine"], "automatic_search_real_city_executed": False,
    "automatic_loop_298_tested_synthetically": True,
    "manual_roles_recorded": list(state["manual"]), "manual_choices_approved": state["manual_approved"],
    "pending": ["Пользователь выбирает и обосновывает А и Б", "Подтверждение ручных вариантов",
                "Реальный полный поиск и выбор В", "Итоговое сравнение А/Б/В и урбанистические выводы"]}
(output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
