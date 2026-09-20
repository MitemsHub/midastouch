"""Pins for the Upcomers instrument screen.

The load-bearing test is ``test_unclassifiable_symbol_is_none_not_guessed``: the
screen ranks instruments by cost, and the cheapest classes are zero-commission
indices, stocks and energies. A classifier that *guesses* a class for an unknown
symbol would silently promote that symbol into the free band and make it look
artificially cheap -- exactly the kind of quiet error that decides a universe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import upcomers_instrument_screen as screen  # noqa: E402

from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    CRYPTO,
    ENERGIES,
    FOREX,
    INDICES,
    METALS,
    STOCKS,
    documented_commission_bps,
    rank_candidates,
)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("symbol,path,expected", [
    ("BTCUSD.nx", "Crypto\\Crypto/Fiat\\BTCUSD.nx", CRYPTO),
    ("ETHUSD.nx", "Crypto\\Crypto/Fiat\\ETHUSD.nx", CRYPTO),
    ("SPCUSD.c", "Indices\\Indices\\SPCUSD.c", INDICES),
    ("DJCUSD.c", "Indices\\Indices\\DJCUSD.c", INDICES),
    ("XAUUSD", "Commodities (Metals)\\Precious Metals\\XAUUSD", METALS),
    ("EURUSD", "Forex\\Major Pairs\\EURUSD", FOREX),
    ("USDJPY", "Forex\\Major Pairs\\USDJPY", FOREX),
    ("AAPL", "Stocks\\US Stocks (NYSE/NASDAQ)\\AAPL", STOCKS),
    ("700.xhkg", "Stocks\\Hong Kong Stocks (HKEX)\\700.xhkg", STOCKS),
])
def test_classify_from_broker_path(symbol, path, expected):
    assert screen.classify_symbol(symbol, path, "") == expected


def test_path_keywords_beat_suffixes():
    """The broker's own category is authoritative; suffixes are only a fallback."""
    # A symbol whose suffix says crypto but whose category says otherwise must
    # follow the category.
    assert screen.classify_symbol("WEIRD.nx", "Forex\\Major Pairs\\WEIRD.nx") == FOREX


def test_unclassifiable_symbol_is_none_not_guessed():
    assert screen.classify_symbol("ZYXWV", "", "") is None
    assert screen.classify_symbol("SOMETHING", "Misc\\Other", "") is None


def test_us_oil_and_gas_are_cost_neutral_whichever_class_they_land_in():
    """Upcomers files USOIL.c/XNGUSD under its Indices table, not Energies.

    That is the venue's own miscategorisation. It is recorded here rather than
    silently corrected because it does not change the cost verdict: both classes
    carry zero commission, so the ranking is unaffected either way.
    """
    bps = documented_commission_bps()
    assert bps[INDICES] == bps[ENERGIES] == 0.0
    landed = screen.classify_symbol("USOIL.c", "Indices\\Indices\\USOIL.c", "")
    assert landed in (INDICES, ENERGIES)


# --------------------------------------------------------------------------- #
# Candidate loading
# --------------------------------------------------------------------------- #


def _write(tmp_path: Path, rows) -> Path:
    p = tmp_path / "cands.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def test_load_candidates_infers_class_and_ranks(tmp_path):
    p = _write(tmp_path, [
        {"symbol": "BTCUSD.nx", "path": "Crypto\\Crypto/Fiat\\BTCUSD.nx",
         "price": 100_000.0, "contract_size": 1.0,
         "atr_price": 500.0, "spread_price": 30.0},
        {"symbol": "SPCUSD.c", "path": "Indices\\Indices\\SPCUSD.c",
         "price": 6_000.0, "contract_size": 1.0,
         "atr_price": 15.0, "spread_price": 0.5},
    ])
    cands = screen.load_candidates(p)
    assert {c.asset_class for c in cands} == {CRYPTO, INDICES}
    ranked = rank_candidates(cands, stop_mult=1.0)
    # The index is priced off a spread alone; crypto pays spread + 8 bps commission.
    assert ranked[0].candidate.symbol == "SPCUSD.c"
    assert ranked[0].cost_r < ranked[1].cost_r


def test_load_candidates_rejects_unclassifiable_row(tmp_path):
    p = _write(tmp_path, [
        {"symbol": "MYSTERY", "price": 1.0, "contract_size": 1.0,
         "atr_price": 1.0, "spread_price": 0.1},
    ])
    with pytest.raises(ValueError, match="cannot be classified"):
        screen.load_candidates(p)


def test_load_candidates_rejects_missing_symbol(tmp_path):
    p = _write(tmp_path, [{"price": 1.0}])
    with pytest.raises(ValueError, match="no 'symbol'"):
        screen.load_candidates(p)


def test_load_candidates_accepts_explicit_class_override(tmp_path):
    """An operator must be able to force a class rather than be blocked by it."""
    p = _write(tmp_path, [
        {"symbol": "MYSTERY", "asset_class": FOREX, "price": 1.10,
         "contract_size": 100_000.0, "atr_price": 0.0008, "spread_price": 0.00001},
    ])
    assert screen.load_candidates(p)[0].asset_class == FOREX


# --------------------------------------------------------------------------- #
# Rendering / offline path
# --------------------------------------------------------------------------- #


def test_commission_table_states_the_crypto_gap():
    text = screen.render_commission_table()
    assert "8.000" in text
    assert "zero commission" in text
    # Crypto must be the most expensive row printed.
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("crypto")]
    assert lines, "crypto row missing from the table"
    assert "8.000" in lines[0]


def test_ranking_render_is_empty_safe():
    assert "nothing to rank" in screen.render_ranking([], (1.0,))


def test_offline_main_ranks_and_writes(tmp_path, capsys):
    src = _write(tmp_path, [
        {"symbol": "XAUUSD", "path": "Commodities (Metals)\\XAUUSD",
         "price": 2_650.0, "contract_size": 100.0,
         "atr_price": 12.0, "spread_price": 0.25},
        {"symbol": "BTCUSD.nx", "path": "Crypto\\BTCUSD.nx",
         "price": 100_000.0, "contract_size": 1.0,
         "atr_price": 500.0, "spread_price": 30.0},
    ])
    out = tmp_path / "ranking.json"
    rc = screen.main(["--candidates", str(src), "--out", str(out),
                      "--stop-mults", "0.5,1,2"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ranked"][0]["symbol"] == "XAUUSD"
    assert set(payload["ranked"][0]["cost_per_r"]) == {"0.5", "1.0", "2.0"}
    # cost per R must worsen as the stop tightens
    cpr = payload["ranked"][0]["cost_per_r"]
    assert cpr["0.5"] == pytest.approx(2 * cpr["1.0"])


def test_commission_table_mode_needs_no_terminal(capsys):
    assert screen.main(["--commission-table"]) == 0
    assert "basis points of notional" in capsys.readouterr().out
