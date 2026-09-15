#!/usr/bin/env python3
"""Write a .set preset into a terminal chart's expert block, exactly.

Why this exists: on 2026-09-13/15 the arm-A chart (FB9A chart01) silently lost
its preset (TP 2.4 + session 6/21 code defaults in place of the certified
TP 1.8 FINAL preset) after WIP re-attach churn. The ledger still proved 1.8
for all closed trades, but the RUNNING engine had drifted. This tool makes
the chart's <inputs> block byte-equal to a certified preset so a boot banner
can be verified against it.

Policy: the preset is the single source of truth. Keys present on the chart
but absent from the preset are REMOVED (the EA then uses its repo default,
which is the certified default). InpMagic is forced per-arm via --magic.

Usage:
  python scripts/set_chart_preset.py --hash FB9A56D6... --chart Default/chart01.chr \
      --preset mql5/MITEMSHUB_AI/MitemshubAI_VOL75_FINAL.set --magic 7788075
"""
import argparse
import datetime
import os
import re
import sys

TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")


def parse_preset(path: str) -> "dict[str, str]":
    vals: dict[str, str] = {}
    for line in open(path, encoding="utf-8-sig", errors="replace"):
        s = line.strip()
        if not s or s.startswith(";") or s.startswith("#"):
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def read_chr(path: str) -> str:
    return open(path, encoding="utf-16", errors="replace").read()


def write_chr(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-16-le", newline="") as f:
        f.write("\ufeff")  # MT5 chart files carry a BOM
        f.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hash", required=True, help="terminal data-folder hash")
    ap.add_argument("--chart", required=True, help="profile-relative path, e.g. Default/chart01.chr")
    ap.add_argument("--preset", required=True, help="repo .set file to apply")
    ap.add_argument("--magic", required=True, help="InpMagic to force")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cpath = os.path.join(TERM_ROOT, args.hash, "MQL5", "Profiles", "Charts", *args.chart.split("/"))
    if not os.path.exists(cpath):
        print(f"FAIL: chart not found: {cpath}")
        return 2
    vals = parse_preset(args.preset)
    if not vals:
        print(f"FAIL: no key=value pairs parsed from {args.preset}")
        return 2
    vals["InpMagic"] = args.magic

    txt = read_chr(cpath)
    m = re.search(r"<inputs>([\s\S]*?)</inputs>", txt)
    if not m:
        print("FAIL: no <inputs> block in chart")
        return 2

    old_keys = [l.split("=", 1)[0].strip() for l in m.group(1).splitlines() if "=" in l]
    new_block = "<inputs>\n" + "".join(f"{k}={v}\n" for k, v in vals.items()) + "</inputs>"

    diffs_add = [k for k in vals if k not in old_keys]
    diffs_del = [k for k in old_keys if k not in vals]
    diffs_chg = [k for k in vals if k in old_keys
                 and dict(l.split("=", 1) for l in m.group(1).splitlines() if "=" in l).get(k, "").strip() != vals[k]]
    print(f"chart: {cpath}")
    print(f"preset: {args.preset} ({len(vals)} inputs)")
    print(f"changes: +{len(diffs_add)} added, -{len(diffs_del)} removed, ~{len(diffs_chg)} changed")
    for tag, ks in (("+", diffs_add), ("-", diffs_del), ("~", diffs_chg)):
        for k in ks[:12]:
            print(f"  {tag} {k}")

    if args.dry_run:
        return 0

    bak = cpath + ".bak_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    open(bak, "wb").write(open(cpath, "rb").read())
    txt = txt[:m.start()] + new_block + txt[m.end():]
    write_chr(cpath, txt)

    # re-parse verify
    back = read_chr(cpath)
    mb = re.search(r"<inputs>([\s\S]*?)</inputs>", back)
    got = dict(l.split("=", 1) for l in mb.group(1).splitlines() if "=" in l)
    bad = [k for k, v in vals.items() if got.get(k, "").strip() != v]
    if bad or set(got) != set(vals):
        print(f"FAIL: re-parse mismatch: {bad[:8]} missing={[k for k in vals if k not in got][:8]}")
        return 1
    print(f"OK: verified byte-exact ({len(vals)} inputs), magic={got['InpMagic']}, backup={os.path.basename(bak)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
