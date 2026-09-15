from scripts.review_v75_shadow_cycle import review


def _summary(trades: list[float], tick_verdict: str = "PASS", orders: bool = False) -> dict:
    return {
        "tick_verdict": tick_verdict,
        "order_submission": orders,
        "shadow_summary": {
            "trades": len(trades),
            "total_r": sum(trades),
            "trade_records": [{"path_r": value} for value in trades],
        },
    }


def test_insufficient_cycle_continues_shadow() -> None:
    result = review(_summary([1.0, -1.0]), min_trades=10)
    assert result["status"] == "CONTINUE_SHADOW"
    assert any(reason.startswith("insufficient-trades") for reason in result["reasons"])


def test_negative_cycle_pauses() -> None:
    result = review(_summary([-1.0] * 10), min_trades=10)
    assert result["status"] == "PAUSE_AND_INVESTIGATE"
    assert result["max_drawdown_r"] == 10.0
    assert any(reason.startswith("negative-or-flat") for reason in result["reasons"])


def test_positive_cycle_can_be_reviewed() -> None:
    result = review(_summary([1.0] * 10), min_trades=10)
    assert result["status"] == "ELIGIBLE_FOR_REVIEW"
    assert result["max_drawdown_r"] == 0.0


def test_order_contract_failure_never_qualifies() -> None:
    result = review(_summary([1.0] * 10, orders=True), min_trades=10)
    assert result["status"] == "PAUSE_AND_INVESTIGATE"
