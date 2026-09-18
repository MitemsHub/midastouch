"""Offline tests for the A2 first-trade watch verifier.

The verifier must be honest in both directions: a healthy trail (consult ->
OPEN, OBSERVE under PASSIVE, budget respected, plain trigger trading at
min-lot risk = the materiality amendment in vivo) verifies green, and each
contract breach (missing consult, VETO under passive, side mismatch, budget
bust) is caught. Synthetic rows only — the live ledger is never touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.a2_first_trade_watch import verify_first_trade  # noqa: E402

JOURNAL_OK = (
    "GL\t0\t21:30:29.137\tMitemshubAI_v28_fwd (Volatility 75 Index,M15)\t"
    "[v28.10] FILTER TABLE: MitemshubAI_filter_table_A2.csv loaded "
    "v=bucket-side-tod-v0 buckets=8 global=0.565 ACTIVATION=ABSENT\n"
    "QQ\t0\t22:14:00.100\tMitemshubAI_v28_fwd (Volatility 75 Index,M15)\t"
    "[v28.10] FILTER CONSULT: side=BUY tod=3 p=0.612 src=BUCKET "
    "activation=ABSENT -> OBSERVE\n"
    "QK\t0\t22:14:00.110\tMitemshubAI_v28_fwd (Volatility 75 Index,M15)\t"
    "[v28.10] OPEN BUY volume=0.0100 entry=46123.45000 SL=44900.00000 "
    "TP=47350.00000 risk=$12.75 risk_src=ENTRY trigger=M30_REVERSED_EXTREME\n")


def healthy_ledger() -> list[list[str]]:
    return [
        ["ERA", "28.10", "1789494700", "pertick-fills"],
        ["FCONSULT", "BUY", "3", "0.6120", "BUCKET", "OBSERVE"],
        ["OPEN", "1789600000", "1789600000", "1", "46123.45000",
         "44900.00000", "47350.00000", "0.01", "12.75", "1000.00",
         "7788075", "A2"],
    ]


def test_healthy_trail_verifies_green_with_in_vivo_materiality() -> None:
    v = verify_first_trade(healthy_ledger(), JOURNAL_OK)
    assert v["problems"] == []
    assert v["consult"] == {"side": "BUY", "tod": 3, "p": 0.612,
                            "src": "BUCKET", "decision": "OBSERVE"}
    assert v["journal"]["trigger"] == "M30_REVERSED_EXTREME"
    # plain EXTREME at min-lot risk trading = the amendment working in vivo
    assert v["journal"]["materiality_amendment_in_vivo"] is True


def test_missing_consult_is_caught() -> None:
    rows = healthy_ledger()
    del rows[1]
    v = verify_first_trade(rows, JOURNAL_OK)
    assert any("no FCONSULT row precedes" in p for p in v["problems"])


def test_veto_under_passive_is_caught() -> None:
    rows = healthy_ledger()
    rows[1] = ["FCONSULT", "BUY", "3", "0.2000", "BUCKET", "VETO"]
    v = verify_first_trade(rows, JOURNAL_OK)
    assert any("must only OBSERVE" in p for p in v["problems"])


def test_side_mismatch_is_caught() -> None:
    rows = healthy_ledger()
    # consult claims SELL while the OPEN row (side=1 -> BUY) disagrees
    rows[1] = ["FCONSULT", "SELL", "3", "0.6120", "BUCKET", "OBSERVE"]
    v = verify_first_trade(rows, JOURNAL_OK)
    assert any("side" in p for p in v["problems"])


def test_budget_bust_is_caught() -> None:
    rows = healthy_ledger()
    rows[2][8] = "200.00"
    journal = JOURNAL_OK.replace("risk=$12.75", "risk=$200.00")
    v = verify_first_trade(rows, journal)
    assert any("budget cap" in p for p in v["problems"])
