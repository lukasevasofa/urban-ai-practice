"""Реальные проверки исходной модели и синтетические проверки механики перебора."""

import copy

import numpy as np
import pandas as pd
import pytest

from model import enumerate_candidates, positive_integer, ranked_candidates


def test_baseline_reproduced(model):
    result = model.calculate([])
    assert result["summary"]["population"] == 133000
    assert result["summary"]["capacity"] == 9664
    assert result["summary"]["demand"] == 16015
    assert result["summary"]["served"] == 9203
    assert result["summary"]["unmet"] == 6812
    assert round(result["summary"]["provision_percent"], 2) == 57.46
    assert result["records"] == model.baseline["records"]


@pytest.mark.parametrize("value", [0, -1, 1.5, 600.0, "600", True, None, [], {}])
def test_invalid_capacity(value):
    with pytest.raises(ValueError):
        positive_integer(value)


def test_invalid_plans(model):
    for plan in [None, [{"block_id": -1, "capacity": 5}], [{"block_id": 298, "capacity": 5}],
                 [{"block_id": True, "capacity": 5}], [{"block_id": 1, "capacity": 5}] * 2]:
        with pytest.raises(ValueError):
            model.calculate(plan)


def test_capacity_independence_spillover_and_reset(model):
    # Техническая школа на 17 мест, не ручной сценарий А/Б и не поиск оптимума.
    eligible = model.blocks.index[model.blocks.population.eq(0) & model.blocks.capacity.eq(0)]
    neighbours = model.blocks.index[model.baseline_frame.demand_left.gt(0)]
    bid = next(int(bid) for bid in eligible if (model.matrix.loc[bid, neighbours] <= 15).any())
    plan = [{"block_id": bid, "capacity": 17}]
    before = copy.deepcopy(plan)
    original_capacity = model.blocks.capacity.copy(deep=True)
    result = model.calculate(plan)
    assert plan == before
    assert result["summary"]["capacity_added"] == 17
    assert result["summary"]["capacity"] == 9681
    rows = pd.DataFrame(result["records"]).set_index("block_id")
    assert rows.loc[bid, "capacity"] == rows.loc[bid, "capacity_initial"] + 17
    assert rows.added_capacity.drop(bid).sum() == 0
    assert rows.loc[bid, "demand"] == 0
    assert (rows.drop(bid).provision > rows.drop(bid).provision_initial).any()
    assert model.calculate(plan) == result
    other = model.calculate([{"block_id": bid, "capacity": 3}])
    assert other["summary"]["capacity"] == 9667
    assert model.calculate([]) == model.baseline
    pd.testing.assert_series_equal(model.blocks.capacity, original_capacity)
    assert model.verify_source_files()


def test_manual_and_candidate_use_identical_calculation(model):
    # Один технический кандидат проверяется тем же методом, что ручной ввод; полного поиска Обнинска нет.
    plan = [{"block_id": 2, "capacity": 17}]
    manual = model.calculate(plan)
    candidate = model.calculate(plan)
    assert manual == candidate


def test_multiple_school_additions(model):
    # Два малых технических прироста, не пользовательский сценарий Б по 300 мест.
    result = model.calculate([{"block_id": 2, "capacity": 7}, {"block_id": 3, "capacity": 11}])
    rows = pd.DataFrame(result["records"]).set_index("block_id")
    assert result["summary"]["school_count"] == 2
    assert result["summary"]["capacity"] == 9682
    assert rows.loc[2, "added_capacity"] == 7 and rows.loc[3, "added_capacity"] == 11
    assert rows.added_capacity.drop([2, 3]).sum() == 0
    assert rows.population.sum() == 133000
    assert model.calculate([]) == model.baseline


def test_all_298_independent_candidates_and_ties_synthetic():
    seen, progress_counts = [], []

    def calculate(plan):
        assert len(plan) == 1 and plan[0]["capacity"] == 17
        bid = plan[0]["block_id"]
        seen.append(bid)
        plan.append({"block_id": -1, "capacity": 1})  # Следующая итерация должна получить новый список.
        return {"summary": {"reduction": bid % 3, "unmet": 20 - bid % 3, "capacity": 117}}

    result = enumerate_candidates(list(range(298)), 17, calculate, lambda rows, n: progress_counts.append(n))
    assert seen == list(range(298))
    assert progress_counts == list(range(1, 299))
    assert result["complete"] and result["checked"] == 298
    assert result["best_blocks"] == list(range(2, 298, 3))
    assert sorted(row["block_id"] for row in result["rows"]) == list(range(298))
    assert all(row["capacity"] == 117 for row in result["rows"])
    assert result["rows"][0]["reduction"] == 2


def test_failed_or_cancelled_search_is_not_optimal():
    def calculate(plan):
        if plan[0]["block_id"] == 7:
            raise AssertionError()
        return {"summary": {"reduction": 1}}

    result = enumerate_candidates(list(range(298)), 17, calculate, lambda *_: None)
    assert result["checked"] == 298 and result["errors"] == 1
    assert not result["complete"] and not result["best_blocks"]
    assert any(row.get("error") == "AssertionError" for row in result["rows"])
    counts = []
    result = enumerate_candidates(list(range(298)), 17, calculate,
        lambda rows, n: counts.append(n), cancelled=lambda: len(counts) >= 5)
    assert result["checked"] == 5 and not result["complete"] and not result["best_blocks"]


def test_all_equal_and_negative_reductions():
    rows = [{"block_id": i, "error": None, "reduction": -2} for i in range(298)]
    ordered, best = ranked_candidates(rows, 298)
    assert best == list(range(298)) and len(ordered) == 298
    assert ranked_candidates(rows[:297], 298)[1] == []
