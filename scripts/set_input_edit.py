#!/usr/bin/env python3
"""Read or edit a single key in an MT5 .set file — byte-precise and fail-closed.

WHY THIS EXISTS. Presets are the deployment surface for this project: an EA
attached to a live chart takes its behaviour from the .set on the chart, not
from the source defaults. Hand-editing 30-90 key files is how silent drift
happens, and the 2026-09-17 MIDASTOUCH incidents were exactly that failure
class (an unregistered variant and a bare re-attach both ran unvalidated
configs). This tool makes preset edits line-surgical and idempotent:

  * only the target KEY's line is rewritten; every other byte survives,
    including per-line CRLF/LF endings and any BOM,
  * the key must already exist — a typo'd key is refused, never silently
    appended (MT5 drops unknown keys, so an appended typo would leave the
    chart on code defaults while looking edited),
  * re-running with the same value is a no-op (no write at all),
  * `--comment` lines are inserted ABOVE the key once, then never duplicated.

USAGE
    python scripts/set_input_edit.py <preset.set> --get InpLiveExecution
    python scripts/set_input_edit.py <preset.set> --set InpLiveExecution=false
    python scripts/set_input_edit.py <preset.set> --set InpLiveExecution=false \
        --comment "disarmed 2026-09-19: unvalidated profile" --dry-run

Exit codes: 0 = ok (or already at target), 1 = key missing / parse refused,
2 = bad usage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

COMMENT_PREFIX = "; "
NOTE_MARKER = "; 2026-09-19 SYNTHETIC REVIVAL"


def read_text(path: Path) -> tuple[str, str]:
    """Return (text, encoding) preserving a BOM if the file has one.

    MT5 writes .set files as UTF-8 with no BOM, but hand-edited ones may be
    UTF-16; we must never rewrite a file in a different encoding than we read.
    """
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig"), "utf-8-sig"
    return raw.decode("utf-8", errors="replace"), "utf-8"


def find_key(lines: list[str], key: str) -> int | None:
    """Index of the line declaring `key`, or None. Comment lines never match."""
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if not body or body.lstrip().startswith((";", "#", "[")):
            continue
        name, sep, _ = body.partition("=")
        if sep and name.strip() == key:
            return i
    return None


def line_value(line: str) -> str:
    body = line.rstrip("\r\n")
    _, _, value = body.partition("=")
    return value.strip()


def newline_of(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("preset", help="path to the .set file")
    ap.add_argument("--get", metavar="KEY", help="print the current value and exit")
    ap.add_argument("--set", dest="assign", metavar="KEY=VALUE",
                    help="set KEY to VALUE (must already exist)")
    ap.add_argument("--comment", action="append", default=[],
                    help="comment line to insert above the key (repeatable)")
    ap.add_argument("--anchor", metavar="KEY",
                    help="insert --comment lines above KEY without changing any "
                         "value (citation repairs / provenance notes)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv[1:])

    path = Path(args.preset)
    if not path.is_file():
        print(f"ERROR: not a file: {path}")
        return 1

    text, encoding = read_text(path)
    lines = text.splitlines(keepends=True)

    if args.get:
        i = find_key(lines, args.get)
        if i is None:
            print(f"ERROR: key {args.get!r} not found in {path.name}")
            return 1
        print(line_value(lines[i]))
        return 0

    if args.anchor and not args.assign:
        if not args.comment:
            ap.error("--anchor requires at least one --comment")
        i = find_key(lines, args.anchor)
        if i is None:
            print(f"ERROR: anchor key {args.anchor!r} not found in {path.name}")
            return 1
        to_insert = [COMMENT_PREFIX + c for c in args.comment]
        k = i - 1
        while k >= 0 and lines[k].lstrip().startswith(NOTE_MARKER):
            k -= 1
        del lines[k + 1:i]
        i = k + 1
        nl = newline_of(lines[i])
        lines[i:i] = [c + nl for c in to_insert]
        if args.dry_run:
            print(f"DRY RUN: {path.name} would note above {args.anchor}")
            return 0
        path.write_bytes("".join(lines).encode(encoding))
        print(f"NOTED: {path.name} ({len(to_insert)} comment line(s) above {args.anchor})")
        return 0

    if not args.assign:
        ap.error("--get, --set or --anchor required")

    key, sep, value = args.assign.partition("=")
    key, value = key.strip(), value.strip()
    if not sep or not key:
        ap.error("--set expects KEY=VALUE")

    i = find_key(lines, key)
    if i is None:
        print(f"ERROR: key {key!r} not found in {path.name} — refusing to append "
              f"(MT5 silently drops unknown keys, so an appended key would leave "
              f"the chart running code defaults)")
        return 1

    current = line_value(lines[i])
    if current == value:
        print(f"unchanged: {path.name} {key}={current}")
        return 0

    # Insert comment lines above the key. Idempotency is by construction: any
    # run of OUR OWN marker lines immediately above the key is removed first and
    # replaced by the requested block, so re-running never stacks duplicates.
    to_insert = [COMMENT_PREFIX + c for c in args.comment]
    if to_insert:
        k = i - 1
        while k >= 0 and lines[k].lstrip().startswith(NOTE_MARKER):
            k -= 1
        del lines[k + 1:i]
        i = k + 1
        if find_key(lines, key) != i:
            print(f"ERROR: key {key!r} lost during comment rewrite — refusing")
            return 1
        nl = newline_of(lines[i])
        lines[i:i] = [c + nl for c in to_insert]
        i = find_key(lines, key)
        if i is None:
            print(f"ERROR: key {key!r} lost after comment insert — refusing")
            return 1

    nl = newline_of(lines[i])
    lines[i] = f"{key}={value}{nl}"

    if args.dry_run:
        print(f"DRY RUN: {path.name} {key}: {current} -> {value}")
        return 0

    path.write_bytes("".join(lines).encode(encoding))
    print(f"EDITED: {path.name} {key}: {current} -> {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
