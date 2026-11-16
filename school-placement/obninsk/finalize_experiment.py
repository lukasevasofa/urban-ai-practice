"""Итог эксперимента по сохранённым А/Б/В. Сценарии и исходные данные не перезаписываются."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from model import APP_DIR, SOURCE, Model, np, pd

RESULTS = APP_DIR / "results"
FINAL = RESULTS / "final"
FINAL.mkdir(exist_ok=True)
protected_paths = [p for p in RESULTS.iterdir() if p.is_file() and (
    p.name.startswith(("scenario_", "auto_", "baseline", "latest", "input_manifest")) or p.name == "scenarios.json")]
protected_paths += [p for p in SOURCE.iterdir() if p.is_file()]
protected = {str(p.relative_to(APP_DIR.parents[1])): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in protected_paths}
state = json.loads((RESULTS / "scenarios.json").read_text())
auto_path = RESULTS / state["latest_search"]
auto = json.loads(auto_path.read_text())
assert auto["complete"] and auto["status"] == "complete" and auto["errors"] == 0
assert auto["checked"] == auto["total"] == len(auto["rows"]) == 298
assert sorted(r["block_id"] for r in auto["rows"]) == list(range(298))
assert all(r.get("error") is None and r["capacity_added"] == 600 and r["capacity"] == 10264
           and r["population"] == 133000 and r["demand"] == 16015 for r in auto["rows"])
best_value = max(r["reduction"] for r in auto["rows"])
best = sorted(r["block_id"] for r in auto["rows"] if r["reduction"] == best_value)
assert best == auto["best_blocks"] and len(best) == 69 and best_value == 600
entries = {e["id"]: e for e in state["scenarios"]}
selected = {"A": entries[state["manual"]["A"]], "B": entries[state["manual"]["B"]]}
selected["V"] = max((e for e in state["scenarios"] if e["role"] == "V"), key=lambda e: e["saved_at"])
assert state["manual_approved"] and state["search_started"]
approved = datetime.fromisoformat(state["approved_at"])
assert all(datetime.fromisoformat(selected[r]["saved_at"]) <= approved for r in ["A", "B"])
assert selected["A"]["result"]["schools"] == [{"block_id": 29, "capacity": 600}]
assert selected["B"]["result"]["schools"] == [{"block_id": 66, "capacity": 300}, {"block_id": 96, "capacity": 300}]
assert selected["V"]["result"]["schools"] == [{"block_id": 103, "capacity": 600}]
for entry in selected.values():
    assert json.loads((RESULTS / f"scenario_{entry['id']}.json").read_text()) == entry["result"]
base = json.loads((RESULTS / "baseline.json").read_text())
base_rows = pd.DataFrame(base["records"]).set_index("block_id")
results = {"0": base, **{role: entry["result"] for role, entry in selected.items()}}
labels = {"0": "Исходное состояние", "A": "А", "B": "Б", "V": "В"}
frames = {}
summary_rows, improved_rows, residual_rows, quarter_rows = [], [], [], []
for role, result in results.items():
    frame = pd.DataFrame(result["records"]).set_index("block_id")
    assert frame.index.equals(base_rows.index)
    pd.testing.assert_series_equal(frame.population, base_rows.population)
    pd.testing.assert_series_equal(frame.demand, base_rows.demand)
    assert (frame.served + frame.unmet == frame.demand).all()
    assert frame.served.sum() == result["summary"]["served"]
    assert frame.unmet.sum() == result["summary"]["unmet"]
    assert frame.capacity.sum() == result["summary"]["capacity"]
    expected_capacity = base_rows.capacity.copy()
    for school in result["schools"]:
        expected_capacity.loc[school["block_id"]] += school["capacity"]
    pd.testing.assert_series_equal(frame.capacity, expected_capacity)
    assert np.allclose(frame.provision.dropna(), (frame.served / frame.demand).dropna(), atol=1e-10)
    assert result["summary"]["reduction"] == 6812 - frame.unmet.sum()
    frames[role] = frame
    for bid, row in frame.iterrows():
        item = {"Сценарий": labels[role], "block_id": bid, "Население": row.population,
            "Спрос, мест": row.demand, "Мощность до": row.capacity_initial, "Мощность после": row.capacity,
            "Обеспеченность до, %": row.provision_initial * 100 if pd.notna(row.provision_initial) else None,
            "Обеспеченность после, %": row.provision * 100 if pd.notna(row.provision) else None,
            "Изменение, п.п.": row.delta_provision_pp, "Дефицит до": row.unmet_initial,
            "Дефицит после": row.unmet, "Сокращение дефицита": row.reduction}
        quarter_rows.append(item)
        if row.delta_provision_pp > 1e-8:
            improved_rows.append(item)
        if row.unmet > 0:
            residual_rows.append(item)
    ss = result["summary"]
    summary_rows.append({"Сценарий": labels[role], "ID размещения": ", ".join(str(s["block_id"]) for s in result["schools"]),
        "Новых школ": ss["school_count"], "Новых мест": ss["capacity_added"], "Всего мест": ss["capacity"],
        "Спрос, мест": ss["demand"], "Обслужено": ss["served"], "Обеспеченность, %": ss["provision_percent"],
        "Остаточный дефицит": ss["unmet"], "Сокращение дефицита": ss["reduction"],
        "Улучшено кварталов": ss["improved_blocks"], "Ухудшено кварталов": ss["worsened_blocks"],
        "Обоснование пользователя": selected[role]["reason"] if role != "0" else "Существующая сеть"})


def export(filename: str, rows: list[dict] | pd.DataFrame) -> None:
    """Сохранить отдельную итоговую таблицу в UTF-8 с BOM."""
    pd.DataFrame(rows).to_csv(FINAL / filename, index=False, encoding="utf-8-sig")


export("scenario_comparison.csv", summary_rows)
export("quarters_all_scenarios.csv", quarter_rows)
export("improved_quarters.csv", improved_rows)
export("remaining_deficit.csv", pd.DataFrame(residual_rows).sort_values(["Сценарий", "Дефицит после"], ascending=[True, False]))
export("automatic_all_298.csv", auto["rows"])

# Независимая проверка выбранного В: не меняет сохранённую запись пользователя.
model = Model(output=FINAL / "validation")
recomputed = model.calculate(selected["V"]["result"]["schools"])
pd.testing.assert_frame_equal(pd.DataFrame(recomputed["records"]), pd.DataFrame(selected["V"]["result"]["records"]),
                             check_exact=False, atol=1e-10, rtol=1e-10)
auto_selected = next(r for r in auto["rows"] if r["block_id"] == 103)
check_rows = []
for key, value in recomputed["summary"].items():
    stored = selected["V"]["result"]["summary"][key]
    search_value = auto_selected[key]
    assert abs(value - stored) < 1e-9 and abs(value - search_value) < 1e-9
    check_rows.append({"Показатель": key, "Сохранённый В": stored,
        "Автоматический перебор, квартал 103": search_value, "Повторный ручной расчёт": value, "Совпадает": True})
export("manual_automatic_check.csv", check_rows)
model.write_result("selected_103_recomputed", recomputed)

# Почему одинаковая эффективность возможна без собственного исходного дефицита.
best_details = []
for bid in best:
    row = next(r for r in auto["rows"] if r["block_id"] == bid)
    available = model.matrix.loc[:, bid].le(15)
    best_details.append({"block_id": bid, "Собственный исходный дефицит": int(base_rows.loc[bid, "unmet"]),
        "Исходный остаточный спрос в 15 мин": int(base_rows.loc[available, "unmet"].sum()),
        "Исходный общий спрос в 15 мин": int(base_rows.loc[available, "demand"].sum()),
        "Остаточный дефицит города": row["unmet"], "Сокращение дефицита города": row["reduction"],
        "Улучшено кварталов": row["improved_blocks"], "Ухудшено кварталов": row["worsened_blocks"]})
export("equivalent_optimal_69.csv", best_details)
# Квартал 32 уже есть среди сохранённых оптимальных результатов, это проверка объяснения, не новый поиск.
example = model.calculate([{"block_id": 32, "capacity": 600}])
example_auto = next(r for r in auto["rows"] if r["block_id"] == 32)
assert all(abs(value - example_auto[key]) < 1e-9 for key, value in example["summary"].items())
example_rows = pd.DataFrame(example["records"]).set_index("block_id")
example_rows["Время до квартала 32, мин"] = model.matrix.loc[:, 32]
example_rows["В пределах 15 минут до 32"] = example_rows["Время до квартала 32, мин"].le(15)
export("redistribution_example_32.csv", example_rows.reset_index())
inside = example_rows["В пределах 15 минут до 32"]
inside_gain = int(example_rows.loc[inside, "reduction"].sum())
outside_gain = int(example_rows.loc[~inside, "reduction"].sum())
assert inside_gain + outside_gain == 600

# Никакой сохранённый выбор, результат перебора или входной файл не перезаписан.
for name, digest in protected.items():
    assert hashlib.sha256((APP_DIR.parents[1] / name).read_bytes()).hexdigest() == digest, name
verification = {"status": "passed", "saved_roles_present": ["A", "B", "V"], "full_comparison_rows": 4,
    "automatic_candidates": 298, "automatic_errors": 0, "equivalent_optimal_count": len(best),
    "selected_optimal_block": 103, "manual_recalculation_matches_saved_V_all_298_rows": True,
    "manual_recalculation_matches_automatic_summary": True, "manual_A_is_also_optimal": 29 in best,
    "saved_scenarios_and_sources_unchanged": True, "protected_files": protected,
    "diagnostic_32_inside_gain": inside_gain, "diagnostic_32_outside_gain": outside_gain,
    "new_automatic_search_started": False}
(FINAL / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2))


def n(value: float, decimals: int = 0) -> str:
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def ids(values) -> str:
    return ", ".join(str(int(v)) for v in values)


summary_table = "| Состояние | Кварталы | Новых школ | Новых мест | Всего мест | Обслужено | Обеспеченность | Дефицит | Сокращение | Улучшено кварталов |\n|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
for row in summary_rows:
    summary_table += f"| {row['Сценарий']} | {row['ID размещения'] or '—'} | {row['Новых школ']} | {n(row['Новых мест'])} | {n(row['Всего мест'])} | {n(row['Обслужено'])} | {n(row['Обеспеченность, %'], 2)}% | {n(row['Остаточный дефицит'])} | {n(row['Сокращение дефицита'])} | {row['Улучшено кварталов']} |\n"
improved_table = "| Сценарий | Квартал | Обеспеченность до | После | Дефицит до | После |\n|---|---:|---:|---:|---:|---:|\n"
for row in improved_rows:
    improved_table += f"| {row['Сценарий']} | {row['block_id']} | {n(row['Обеспеченность до, %'], 2)}% | {n(row['Обеспеченность после, %'], 2)}% | {n(row['Дефицит до'])} | {n(row['Дефицит после'])} |\n"
reasons = ""
for role in ["A", "B", "V"]:
    entry = selected[role]
    local = datetime.fromisoformat(entry["saved_at"]).astimezone(ZoneInfo("Europe/Moscow"))
    reasons += f"**{labels[role]} — {entry['name']}**, ID записи `{entry['id']}`, сохранён {local:%d.%m.%Y %H:%M:%S} МСК.\n\n> {entry['reason']}\n\n"
remaining_ids = sorted(frames["A"].index[frames["A"].unmet.gt(0)])
assert all(sorted(frames[r].index[frames[r].unmet.gt(0)]) == remaining_ids for r in ["B", "V"])
assert remaining_ids == sorted(base_rows.index[base_rows.unmet.gt(0)])
zero_own = sum(item["Собственный исходный дефицит"] == 0 for item in best_details)
large_own = sum(item["Собственный исходный дефицит"] >= 600 for item in best_details)
small_catch = sum(item["Исходный остаточный спрос в 15 мин"] < 600 for item in best_details)
peak_lines = "\n".join(f"- {labels[r]}: "+"; ".join(f"№{int(bid)} — {n(row.unmet)} мест" for bid,row in frames[r].nlargest(5,"unmet").iterrows())+"."
                       for r in ["A","B","V"])
report = f"""# Практическая работа №3. Обнинск — итог эксперимента

Эксперимент завершён. Отчёт составлен по фактическим сохранённым результатам, без изменения выбранных школ,
исходных данных, параметров и интерфейса. Все три пользовательских сценария присутствуют в реестре приложения
`results/scenarios.json` и итоговой таблице вместе с исходным состоянием.

## 1. Варианты и порядок эксперимента

{reasons}
Ручные записи А и Б сохранены до подтверждения выбора `{state['approved_at']}` (UTC).
Реестр подтверждает `manual_approved=true`, а API допускает поиск только после этого действия.
Пользователь также подтвердил соблюдение последовательности. Отдельного времени старта в JSON перебора нет;
оно не выдумывается. В сохраняется после полного перебора. Обоснования выше приведены без редактирования.

Проверен `{auto_path.name}`: **298 различных кварталов 0…297, 298 результатов, 0 ошибок, статус complete**.
Все варианты имеют одно и то же население 133 000, спрос 16 015 и мощность исходной сети 9 664 + 600 = 10 264 места.
Накопления новых мест между кандидатами в сохранённых результатах нет.

## 2. Итоговая сравнительная таблица

{summary_table}
Во всех вариантах прирост мощности одинаков — 600 мест. Обеспеченность увеличивается с 57,46 до 61,21%,
то есть на **{n(9803 / 16015 * 100 - 9203 / 16015 * 100, 2)} процентного пункта**. На {n(600 / 6812 * 100, 2)}% сокращается
исходный дефицит. Не следует называть прирост в п.п. относительным процентом обеспеченности.
Ухудшившихся кварталов в А, Б и В нет. Совпадение общих итогов не означает совпадения их пространственного эффекта.

## 3. Ответы на вопросы задания

### Какой вариант наиболее эффективен?

**По заданному критерию все три равноэффективны:** каждый сокращает суммарный дефицит на 600 мест до 6 212.
Единственного победителя среди А, Б и В нет. По числу кварталов с улучшением Б охватывает два, А и выбранный В — по одному.
Это дополнительное различие распределения эффекта, но не выигрыш Б по суммарному дефициту.
Экономическую эффективность, стоимость строительства и наличие участков модель не оценивает.

### Совпал ли ручной выбор с автоматическим?

Если сравнивать конкретные выбранные ID, **нет: А — 29, В — 103**. Но квартал **29 входит в полный набор
69 оптимальных кварталов**. Следовательно, ручной вариант А также оптимален по основному критерию;
автопоиск не выявил превосходства 103 над 29. Он выявил группу равных решений.

### Где обеспеченность повысилась?

{improved_table}
В трёх выбранных вариантах весь дополнительный обслуженный спрос приходится на кварталы размещения:
А — 29, Б — 66 и 96, В — 103. Это согласуется с `self_supply=True`: новый ресурс первым покрывает спрос своего квартала.
В остальных кварталах данных трёх сценариев обеспеченность не изменилась. Это не означает, что модель вообще
не учитывает соседей: другие кандидаты полного перебора улучшают от 1 до 22 кварталов.
Подробные строки — `results/final/improved_quarters.csv` и `quarters_all_scenarios.csv`.

### Где сохранился дефицит?

В исходном состоянии и в каждом из трёх сценариев остаточный дефицит есть в одних и тех же **95 кварталах**.
Ни один из них не стал полностью обеспеченным; снизилась тяжесть дефицита в перечисленных выше местах.
Полный список ID:

{ids(remaining_ids)}.

Наибольшие остатки по сценариям:

{peak_lines}

Все количества по каждому кварталу и сценарию находятся в `results/final/remaining_deficit.csv`.
Остаток 6 212 — сумма пространственно неудовлетворённого спроса, а не простое вычитание мощности из потребности:
16 015 − 10 264 = 5 751, что меньше фактического модельного остатка. Разница **461 место** соответствует
неиспользованной мощности сети при текущем распределении и доступности.

### Когда две школы по 300 мест лучше одной на 600?

В данном эксперименте **Б не лучше А или В по суммарному сокращению дефицита**: все дополнительные 600 мест
дают 600 дополнительных обслуженных заявок. Б пространственно распределяет улучшение между двумя кварталами;
матрица даёт **{n(model.matrix.loc[66,96], 2)} минуты** между 66 и 96, что больше порога 15 минут.

В общем случае две школы могут быть эффективнее, если остаточный спрос разделён между удалёнными группами,
одна школа не достигает обеих за 15 минут и часть её мощности не используется, а две меньшие достигают каждой
группы. Этого преимущества по главной метрике выбранные результаты не показали. Результат не доказывает
универсального преимущества схемы 300+300, и автоматического подбора лучшей пары здесь не было.

### Какие ограничения влияют на выводы?

Население — калиброванное учебное распределение ориентира на 01.01.2025 по застройке OSM 2026, не официальная
численность кварталов; постоянная заселённость садов принята нулевой. Большинство школьных мощностей оценено
по площади / 18 м² на место; частные и специальные учреждения не покрывают неограниченный спрос.
Граф самостоятельно построен по пешеходной сети OSM, скорость 4,5 км/ч, порог 15 минут; подходы к узлам,
внутриквартальные пути, особенности школьных входов и возрастная структура не моделируются.
Крупные кварталы обобщают внутренние различия. `self_supply=True` сначала распределяет места внутри своего квартала.
BlocksNet оптимизирует взвешенное распределение; результаты отражают его приоритеты, а не гарантируют равный
выигрыш всем районам. Школы на 600 и 300 мест не различаются по программе, землеёмкости и цене.
Ни один из 69 кварталов не подтверждён как подходящий земельный участок.

## 4. Почему оптимальными оказались 69 кварталов?

Это **реальная точная ничья по числу мест**, а не ошибка округления процентов: у всех 69 обслужено 9 803,
остаток 6 212, сокращение ровно 600. Перебор всех 298 подтверждён, ни один кандидат не дал большего сокращения.
Для множества положений новой школы доступность и перераспределение спроса позволяют получить одинаковый
общий эффект от прибавленных 600 мест. Главный критерий не различает, какие именно жители и кварталы выигрывают,
насколько короче их маршруты и насколько реалистично строительство.

Только **{large_own}** из 69 — кварталы с собственным исходным дефицитом не менее 600: **29, 66, 103**.
У **{zero_own}** собственный исходный дефицит равен нулю, но школа может обслуживать соседей и менять распределение
существующих мест. Поэтому искать только крупнейший собственный дефицит было бы неправильно.
Число улучшившихся кварталов среди 69 равноценных вариантов различается от 1 до 22.

Нельзя объяснять все ничьи только наличием 600 исходных необслуженных заявок в ближайших 15 минутах:
у **{small_catch}** оптимальных кварталов такой остаточный спрос меньше 600. Проверен показательный сохранённый
кандидат **32**: первоначальный остаточный спрос в его 15-минутном контексте — **383**, но общий выигрыш — 600.
Повторный расчёт тем же методом совпал с сохранённой строкой перебора. Из них **{inside_gain}** дополнительных
обслуженных заявок приходятся на кварталы в пределах 15 минут до 32, **{outside_gain}** — на кварталы за этим пределом.
Это **не разрешение ехать в новую школу дольше 15 минут**: при полном пересчёте часть ранее обслуженных жителей
переходит к новой мощности, высвобождая существующие места для других кварталов. Возникает эффект перераспределения.
Проверочные строки с временами и изменениями — `results/final/redistribution_example_32.csv`.

Все 69 ID: **{ids(best)}**.
Полная таблица с собственным спросом, 15-минутным контекстом и эффектом — `results/final/equivalent_optimal_69.csv`.
Их равенство относится исключительно к принятому критерию и параметрам модели.

## 5. Проверка совпадения ручного и автоматического расчёта

Для выбранного оптимального **103** независимо вызвана та же функция ручного сценария: одна школа 600 мест,
исходные население, мощности, матрица и параметры. Сохранённый В и повторный ручной расчёт совпали **по всем
298 поквартальным строкам**, а все общие показатели совпали со строкой 103 полного автоматического перебора.
В частности: мощность 10 264, обслужено 9 803, обеспеченность 61,21%, дефицит 6 212, сокращение 600,
улучшен один квартал. Сравнение сохранено в `manual_automatic_check.csv`.

Проверки не сохраняли новые сценарии в пользовательский реестр и не запускали новый перебор.
Контрольные суммы исходных файлов, `scenarios.json`, всех сохранённых сценариев, исходного расчёта и файла
полного поиска до и после обработки совпали. Итоговый машинный протокол — `results/final/verification.json`.
Интерфейс и методика расчёта не изменены.

## 6. Итоговые файлы

- `results/final/scenario_comparison.csv` — исходное состояние, А, Б и В со всеми итоговыми метриками и обоснованиями.
- `results/final/quarters_all_scenarios.csv` — все 298 кварталов для четырёх состояний.
- `results/final/improved_quarters.csv` — конкретные улучшившиеся кварталы и показатели до/после.
- `results/final/remaining_deficit.csv` — все кварталы с остаточным дефицитом и его величиной.
- `results/final/automatic_all_298.csv` — фактические строки полного перебора.
- `results/final/equivalent_optimal_69.csv` — все равные оптимумы с диагностикой доступного спроса.
- `results/final/manual_automatic_check.csv` — проверка выбранного 103.
- `results/final/redistribution_example_32.csv` — разбор эффекта перераспределения.
- `results/final/validation/` — отдельный воспроизведённый исходный расчёт для проверки, без перезаписи пользовательских результатов.

CSV сохранены в UTF-8 с BOM, разделитель — запятая; проценты представлены числовыми значениями.
Повторное формирование: `.venv/bin/python school-placement/obninsk/finalize_experiment.py`.

Задание: https://mvin8.github.io/ai-technologies-in-urbanism/content/practice/practice-03.html.
Исходная методика: `school_parameters.json` и окончательные данные `practice3/`.
Браузерные проверки приложения до эксперимента описаны в `results/browser_check.json`, 19 Python-тестов —
в `results/python_tests.xml`; они не выдаются за доказательство результатов эксперимента, проверенного отдельно выше.
"""
(APP_DIR / "REPORT.md").write_text(report)
(FINAL / "REPORT.md").write_text(report)
print(json.dumps({key: value for key, value in verification.items() if key != "protected_files"}, ensure_ascii=False, indent=2))
