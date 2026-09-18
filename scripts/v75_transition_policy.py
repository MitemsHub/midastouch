#!/usr/bin/env python3
"""Research-only policy for filtering unstable Volatility 75 transitions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


# These are deliberately vetoes, not entry directions. They came from the
# cross-window transition analysis and must not be treated as universal alpha.
VETO_STATES = {
    "TRANSITION_EXPANSION_UP",
    "TRANSITION_EXPANSION_DOWN",
    "TRANSITION_FAILED_MOVE_DOWN",
}


def allowed(state: str) -> bool:
    """Return whether a transition state may pass to a downstream router."""
    return state not in VETO_STATES


def apply_policy(analysis: dict) -> dict:
    results = []
    for row in analysis["results"]:
        kept = allowed(row["state"])
        results.append({**row, "transition_policy": "ALLOW" if kept else "VETO"})
    return {
        "schema": "mitemshub.v75.transition-policy.v1",
        "research_only": True,
        "policy": "veto unstable expansion and failed-down transition states; never create a direction",
        "veto_states": sorted(VETO_STATES),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = apply_policy(json.loads(args.analysis.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("veto states:", ", ".join(result["veto_states"]))
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
