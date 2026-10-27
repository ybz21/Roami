"""Optional backtest summaries agree with the independently verified trade ledger."""

import copy

import pytest

from roami_agent.improvement.authored_grading import corrected_backtest_matches


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "no_summaries",
        "initial_cash",
        "fee",
        "slippage",
        "final_cash",
        "final_quantity",
        "final_equity",
        "description",
        "unknown_field",
        "wrong_trade",
        "boolean_number",
    ],
)
def test_optional_summaries_cannot_contradict_core_results(closed, fault):
    trades = [{"side": "buy", "price": 10, "quantity": 900, "fee": 9}]
    if closed:
        trades.append({"side": "sell", "price": 12, "quantity": 900, "fee": 10.8})
    final_cash = 11780.2 if closed else 991
    final_equity = 11780.2 if closed else 10891
    expected = {
        "receipt": "fixture",
        "strategy": {"trades": trades, "equity": [10000, 9991, final_equity]},
    }
    prices = {"initial_cash": 10000, "fee": 0.001, "slippage": 0.001}
    actual = copy.deepcopy(expected)
    summaries = {
        **prices,
        "final_cash": final_cash,
        "final_quantity": 0 if closed else 900,
        "final_equity": final_equity,
        "description": "Causal backtest",
    }
    if fault != "no_summaries":
        actual["strategy"].update(summaries)
    if fault in prices or fault in {"final_cash", "final_quantity", "final_equity"}:
        actual["strategy"][fault] += 1
    elif fault == "description":
        actual["strategy"]["description"] = True
    elif fault == "unknown_field":
        actual["strategy"]["guaranteed_return"] = True
    elif fault == "wrong_trade":
        actual["strategy"]["trades"][0]["quantity"] += 1
    elif fault == "boolean_number":
        actual["strategy"]["final_cash"] = True
    original = copy.deepcopy(actual)
    assert corrected_backtest_matches(actual, expected, prices) is (fault in {None, "no_summaries"})
    assert actual == original
