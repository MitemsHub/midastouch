#!/usr/bin/env python3
"""Read a research source with a real browser — and refuse what must be refused.

WHY THIS TOOL EXISTS. Reading a paper is legitimate; a script that can be pointed at any site
is how a program ends up scraping one. So the limits are IN the tool, not in a convention:

1. **robots.txt first**, read the way a browser reads it. A path the file disallows is refused.
2. **An explicit block page is a REFUSAL, never retried differently.** Measured 2026-09-21:
   SSRN (Elsevier Content Protection) answers every automated client — including a real
   Chromium — with HTTP 403 and the words "We have detected that you may be using an automated
   script or search engine our site does not support. Please retry using an alternate way of
   accessing our site." That is a stated policy, not a puzzle: the tool reports it and stops.
   Defeating it would take fingerprint spoofing, and a repository whose whole discipline is
   "refuse what you cannot justify" does not do that to read a paper.
3. **One request at a time, a minimum gap apart, a hard cap per run.** No crawling, no
   recursion, no link following.
4. **No credentials, no logins.** A page that needs an account is out of scope.
5. **Cache under `artifacts/research_cache/`** (gitignored): fetched bytes are working files,
   and a paper is never committed — the documents in `docs/` carry our reading of it.

WHAT IT IS FOR. Sources that permit automation: arXiv, NBER, RePEc, PubMed Central, university
and author pages, journal open-access. PDFs are extracted with pypdf so they can be read as
text.

USAGE
    python scripts/research_fetch.py URL [URL ...] [--chars 9000] [--save]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "artifacts" / "research_cache"

MIN_GAP_S = 3.0          # between requests, so a run cannot look like a burst
MAX_PAGES = 8            # per run: reading a few papers, not walking a site
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0 Safari/537.36")

#: Wording that means "automated clients are refused", from the publishers who use it. A
#: match is terminal: the tool does not retry with a different user agent, and it says why.
BLOCK_MARKERS = (
    "content blocked",
    "detected that you may be using an automated script",
    "our site does not support",
    "access denied",
    "just a moment",                 # Cloudflare interstitial
    "attention required",
    "please enable javascript and cookies to continue",
    "captcha",
)
#: Pages that need an account are out of scope rather than attempted.
LOGIN_MARKERS = ("sign in to continue", "log in to continue", "member sign in", "subscribe to view")


def looks_blocked(text: str) -> str | None:
    """The block marker this response contains, or None. Case-insensitive, first match wins."""
    low = (text or "")[:6000].lower()
    for m in BLOCK_MARKERS:
        if m in low:
            return m
    return None


def looks_gated(text: str) -> str | None:
    low = (text or "")[:6000].lower()
    for m in LOGIN_MARKERS:
        if m in low:
            return m
    return None


def robots_verdict(robots_text: str, path: str, ua: str = "*") -> tuple[bool, str]:
    """(allowed, reason) for `path` against a robots.txt body.

    Implements the group semantics that matter for a single user agent: an empty or absent
    body allows everything; the most specific matching group wins; within a group the LONGEST
    matching Disallow/Allow path wins, and Allow wins a tie (the Robots Exclusion Protocol's
    rule, and the conservative reading is to honour it).
    """
    if not robots_text.strip():
        return True, "no robots.txt directives (absent or empty)"
    groups: dict[str, list[tuple[str, str]]] = {}
    current: list[str] = []
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if not value:
                continue
            if current and value.lower() == ua.lower():
                break                      # same agent listed twice: first group governs
            current.append(value)
            groups.setdefault(value, [])
        elif field in ("disallow", "allow") and current:
            for agent in current:
                groups.setdefault(agent, []).append((field, value))
    rules = groups.get(ua) or groups.get("*") or []
    if not rules:
        return True, f"no rules for user-agent {ua!r}"
    # The longest matching path wins; Allow wins a tie (the Robots Exclusion Protocol).
    best_len, best_allow, best_rule = -1, True, ""
    for field, value in rules:
        if value == "":                     # "Disallow:" with nothing = allow everything
            continue
        pattern = re.escape(value).replace(r"\*", ".*")
        if not re.match(pattern, path):
            continue
        allow = field == "allow"
        if len(value) > best_len or (len(value) == best_len and allow):
            best_len, best_allow, best_rule = len(value), allow, value
    if best_len < 0:
        return True, "no rule matches this path"
    return best_allow, f"{'Allow' if best_allow else 'Disallow'}: {best_rule}"


class BrowserTransport:
    """The real transport: one Chromium, downloaded bytes and rendered text."""

    def __init__(self) -> None:
        from playwright.sync_api import sync_playwright   # lazy: the suite needs no browser
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._ctx = self._browser.new_context(user_agent=UA)

    def get(self, url: str) -> tuple[int, str, bytes]:
        r = self._ctx.request.get(url, timeout=60000)
        return r.status, r.headers.get("content-type", ""), r.body()

    def text(self, url: str) -> tuple[int, str]:
        """Rendered text for a page, or the raw body's text when it is not HTML."""
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, timeout=60000, wait_until="domcontentloaded")
            status = resp.status if resp else 0
            return status, page.inner_text("body")
        finally:
            page.close()

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()


def pdf_text(body: bytes, pages: int = 12) -> str:
    """Text of the first `pages` pages. Font-decoding chatter is silenced: it is pypdf
    narrating its own internals, and a run that prints fifty lines of it buries the paper."""
    import io
    import logging
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(io.BytesIO(body))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:pages])


def cache_write(url: str, body: bytes) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", urllib.parse.urlparse(url).path.strip("/")) or "index"
    p = CACHE / (name[-120:] or "index")
    p.write_bytes(body)
    return p


def read_one(transport, url: str, chars: int, *, offset: int = 0, pages: int = 12,
             save: bool = False) -> dict:
    """Fetch one URL, honouring robots, block pages and login walls. Never raises on refusal.

    `offset` reads a window deeper into a long document — a deck's findings sit at char
    40,000 while its title slide sits at 0, and re-fetching the head to reach them wastes
    the fetch. `pages` is how far into a PDF to extract, for the same reason."""
    out = {"url": url, "kind": "", "text": "", "note": ""}
    parts = urllib.parse.urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        status, rtext = transport.text(robots_url)
        verdict = looks_blocked(rtext)
        if status in (401, 403) or verdict:
            out.update(kind="refused",
                       note=(f"robots.txt is itself refused (HTTP {status}"
                             + (f", marker {verdict!r}" if verdict else "") + ") — the site "
                             "declines automated clients, so this tool stops here"))
            return out
        allowed, why = robots_verdict(rtext if status == 200 else "", parts.path or "/")
        if not allowed:
            out.update(kind="refused", note=f"robots.txt {why} for {parts.path}")
            return out
    except Exception as exc:                       # pragma: no cover — network dependent
        out.update(kind="error", note=f"robots.txt unreachable: {type(exc).__name__}: {exc}")
        return out

    time.sleep(MIN_GAP_S)
    try:
        status, ctype, body = transport.get(url)
    except Exception as exc:                       # pragma: no cover
        out.update(kind="error", note=f"{type(exc).__name__}: {str(exc)[:200]}")
        return out
    if status in (401, 403):
        out.update(kind="refused", note=f"HTTP {status} — the server declined the request")
        return out
    if "pdf" in ctype.lower() or body[:4] == b"%PDF":
        if save:
            out["cached"] = str(cache_write(url, body))
        try:
            text = pdf_text(body, pages)
        except Exception as exc:
            out.update(kind="error", note=f"PDF not extractable: {type(exc).__name__}: {exc}")
            return out
        out.update(kind="pdf", text=text[offset:offset + chars])
        out["chars_total"] = len(text)
        return out
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:                              # pragma: no cover
        out.update(kind="error", note="undecodable body")
        return out
    marker = looks_blocked(text)
    if marker:
        out.update(kind="refused",
                   note=(f"the page is a BLOCK page (marker {marker!r}) — an automated client "
                         "is refused by policy, and this tool does not try to look like "
                         "something else"))
        return out
    gate = looks_gated(text)
    if gate:
        out.update(kind="gated", note=f"needs an account ({gate!r}) — out of scope")
        return out
    text = re.sub(r"\n{3,}", "\n\n", text)
    out.update(kind="html", text=text[offset:offset + chars])
    out["chars_total"] = len(text)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--chars", type=int, default=8000)
    ap.add_argument("--from", dest="offset", type=int, default=0,
                    help="character offset into the document (read a window deeper in)")
    ap.add_argument("--pages", type=int, default=12,
                    help="how many PDF pages to extract (default 12)")
    ap.add_argument("--save", action="store_true", help="cache fetched bytes under artifacts/")
    args = ap.parse_args(argv)
    # A paper's text is full of characters a Windows console codec cannot represent; replace
    # them rather than crashing on an excerpt.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):            # pragma: no cover
        pass
    if len(args.urls) > MAX_PAGES:
        print(f"REFUSING: {len(args.urls)} URLs exceeds the {MAX_PAGES}-page limit for one run "
              f"(this tool reads papers, it does not crawl sites)")
        return 2

    transport = BrowserTransport()
    try:
        for i, url in enumerate(args.urls):
            r = read_one(transport, url, args.chars, offset=args.offset,
                         pages=args.pages, save=args.save)
            print(f"\n{'=' * 78}\n{r['kind'].upper()}  {url}")
            if r.get("chars_total"):
                print(f"  window: chars {args.offset}-{args.offset + args.chars} "
                      f"of {r['chars_total']}")
            if r["note"]:
                print(f"  note: {r['note']}")
            if r.get("cached"):
                print(f"  cached: {r['cached']}")
            if r["text"]:
                print(r["text"])
            if i + 1 < len(args.urls):
                time.sleep(MIN_GAP_S)
    finally:
        transport.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
