"""The reader's limits: robots precedence, block pages, login walls, the per-run cap.

WHY THIS FILE EXISTS. `scripts/research_fetch.py` is the only thing in this repository that
fetches third-party pages, and its whole value is in what it refuses — a reader that quietly
ignores a Disallow, or that retries a block page with a different user agent, is a scraper
with a comment on top. The refusals are the feature, so they are pinned here rather than
trusted.

The tests are pure-function and offline: no browser is launched, no network is touched. The
live transport (Playwright) is imported lazily inside `BrowserTransport`, and one test below
pins that laziness, because the suite must not acquire a 130 MB dependency to stay green.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import research_fetch as rf  # noqa: E402


# --- robots.txt precedence -------------------------------------------------------------

def test_absent_robots_allows_everything() -> None:
    allowed, why = rf.robots_verdict("", "/anything")
    assert allowed and "no robots.txt" in why


def test_disallow_blocks_a_prefix_and_its_children() -> None:
    body = "User-agent: *\nDisallow: /private\n"
    assert rf.robots_verdict(body, "/private")[0] is False
    assert rf.robots_verdict(body, "/private/notes")[0] is False
    assert rf.robots_verdict(body, "/public")[0] is True


def test_empty_disallow_is_an_allow_not_a_block() -> None:
    """`Disallow:` with nothing after it means "no restriction". Reading it as a block is a
    silent refusal to read a source that permits reading."""
    assert rf.robots_verdict("User-agent: *\nDisallow:\n", "/x")[0] is True


def test_longest_match_wins_and_allow_wins_a_tie() -> None:
    """The Robots Exclusion Protocol's own rule. `Disallow: /` must not swallow an explicit
    `Allow: /docs`, and an equal-length Allow must not be overridden by a Disallow."""
    body = "User-agent: *\nDisallow: /\nAllow: /docs\n"
    assert rf.robots_verdict(body, "/docs/paper.pdf")[0] is True
    assert rf.robots_verdict(body, "/secret")[0] is False
    tie = "User-agent: *\nDisallow: /x\nAllow: /x\n"
    assert rf.robots_verdict(tie, "/x")[0] is True


def test_a_group_for_another_agent_is_not_our_group() -> None:
    body = "User-agent: SomeOtherBot\nDisallow: /\n"
    allowed, why = rf.robots_verdict(body, "/paper")
    assert allowed and "no rules for user-agent" in why


# --- block pages and login walls --------------------------------------------------------

def test_the_ssrn_refusal_wording_is_recognised() -> None:
    """The exact text SSRN/Elsevier returned on 2026-09-21. If a publisher states a policy in
    words, matching those words is the whole point of the marker list."""
    page = ("Content Blocked\n! We have detected that you may be using an automated script "
            "or search engine our site does not support. Please retry using an alternate way "
            "of accessing our site.")
    assert rf.looks_blocked(page) is not None


def test_a_login_wall_is_gated_not_attempted() -> None:
    assert rf.looks_gated("<h1>Sign in to continue</h1>") is not None
    assert rf.looks_blocked("<h1>Sign in to continue</h1>") is None


class FakeTransport:
    """The smallest thing that satisfies the transport protocol."""

    def __init__(self, robots=(200, ""), page=(200, "text/html", b"<html>plain</html>")):
        self.robots, self.page = robots, page
        self.gets: list[str] = []

    def text(self, url: str) -> tuple[int, str]:
        return self.robots

    def get(self, url: str) -> tuple[int, str, bytes]:
        self.gets.append(url)
        return self.page


def test_a_robots_txt_that_is_itself_refused_stops_the_tool() -> None:
    t = FakeTransport(robots=(403, "Content Blocked"))
    out = rf.read_one(t, "https://example.invalid/paper.pdf", 100)
    assert out["kind"] == "refused"
    assert "robots.txt is itself refused" in out["note"]
    assert t.gets == []                      # nothing was fetched


def test_a_disallowed_path_is_never_fetched() -> None:
    t = FakeTransport(robots=(200, "User-agent: *\nDisallow: /private\n"))
    out = rf.read_one(t, "https://example.invalid/private/paper.pdf", 100)
    assert out["kind"] == "refused"
    assert "Disallow: /private" in out["note"]
    assert t.gets == []


def test_a_block_page_body_is_a_refusal_not_a_retry() -> None:
    t = FakeTransport(page=(200, "text/html", b"Access denied"))
    out = rf.read_one(t, "https://example.invalid/paper", 100)
    assert out["kind"] == "refused"
    assert "BLOCK page" in out["note"]


def test_an_http_403_on_the_document_is_a_refusal() -> None:
    t = FakeTransport(page=(403, "text/html", b""))
    out = rf.read_one(t, "https://example.invalid/paper", 100)
    assert out["kind"] == "refused" and "HTTP 403" in out["note"]


def test_a_clean_page_is_read_and_a_window_slices_into_it() -> None:
    t = FakeTransport(page=(200, "text/html", b"abcdefghij"))
    out = rf.read_one(t, "https://example.invalid/ok", 4, offset=3)
    assert out["kind"] == "html" and out["text"] == "defg"
    assert out["chars_total"] == 10


# --- the run-level caps -----------------------------------------------------------------

def test_a_run_over_the_page_cap_refuses_without_starting_a_browser() -> None:
    urls = [f"https://example.invalid/{i}" for i in range(rf.MAX_PAGES + 1)]
    rc = rf.main(urls)
    assert rc == 2


def test_the_cap_is_small_enough_to_be_a_reading_limit() -> None:
    assert 1 <= rf.MAX_PAGES <= 12
    assert rf.MIN_GAP_S >= 1.0


def test_importing_the_tool_does_not_require_a_browser() -> None:
    """Playwright must stay behind `BrowserTransport.__init__`: a suite that needs a 130 MB
    browser to import a helper is a suite that stops running."""
    src = (ROOT / "scripts" / "research_fetch.py").read_text(encoding="utf-8")
    assert "from playwright.sync_api import sync_playwright" in src
    body = src.split("class BrowserTransport", 1)[1]
    head = src.split("class BrowserTransport", 1)[0]
    assert "playwright" not in head, "the browser import escaped to module scope"
    assert "from playwright" in body.split("def get", 1)[0]


def test_the_script_runs_and_reports_its_own_help() -> None:
    """A one-line smoke test that the file is still executable as the docs describe it."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "research_fetch.py"), "--help"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    assert "--chars" in r.stdout and "--pages" in r.stdout


@pytest.mark.parametrize("marker", ["content blocked", "access denied", "just a moment"])
def test_known_block_marker_variants(marker: str) -> None:
    assert rf.looks_blocked(f"...{marker}...") == marker
