# V75 Router Research Architecture

This scope is intentionally research-only; it does not feed the EA or submit orders.

## Data flow

```text
raw M15/H1 bars + ticks
        |
        v
v75_opportunity_map.py  -- builds one causal opportunity-map snapshot per cost multiplier
        |
        v75_geometry_policy_snapshot.py  -- loads/validates snapshots, owns map cache,
        |                                    hashes, and provenance records
        v75_geometry_policy.py  -- owns pocket discovery, policy fitting, and validation gates
        |
        v75_geometry_policy_engine.py  -- owns chronological train/validation/test fold state
        |
        v75_router_core.py  -- owns Pocket identity, geometry contract, and the one
        |                       frozen-portfolio lifecycle
        v
v75_geometry_policy_selector.py  -- thin CLI argument/rendering facade
        |
        +--> v75_shadow_replay.py -- typed presentation of the core lifecycle events
```

## Ownership rules

- `v75_opportunity_map.py` owns raw-data transformation into map metrics and map-specific
  parameters. It never chooses a policy or defines exit geometry.
- `v75_router_core.py` owns the exit-geometry contract, `Pocket`, pocket/setup keys,
  geometry-to-R conversion, exact feature matching, chronological non-overlap, family
  health invalidation, and frozen-portfolio execution. This is the only owner of the
  execution lifecycle.
- `v75_geometry_policy_snapshot.py` owns snapshot loading, exact data/cost validation,
  deterministic fingerprints, one-map-per-multiplier caching, and provenance assembly.
  No fold or policy code owns snapshot state.
- `v75_geometry_policy.py` owns policy behavior: discovery, original/calibrated fitting,
  validation scoring, stress scoring, and tie-breaking. It delegates execution semantics
  to `v75_router_core.py`.
- `v75_geometry_policy_engine.py` owns the rolling fold lifecycle: train, validation,
  stress validation, frozen policy choice, untouched test evaluation, and result assembly.
  It does not parse CLI arguments or print output.
- `v75_geometry_policy_selector.py` owns only CLI argument parsing, artifact rendering,
  and compatibility re-exports for existing callers. It delegates computation to the
  engine and snapshot module.
- `v75_shadow_replay.py` owns only typed presentation of decisions. It does not implement
  a second evaluator: it requests the event trace from `v75_router_core.py`.
- The core evaluator can suppress event allocation for scoring. Replay opts into events;
  both paths therefore execute the same state transitions without paying presentation
  overhead during policy comparison.
- The test window is never passed into fitting or policy choice. Both frozen policy
  portfolios are reported for audit comparison, but only validation can select.

## Compatibility boundary

The positional `run(...)` API and existing imports from
`v75_geometry_policy_selector.py` remain available. New callers may use the explicit
`map_snapshot`/`stress_snapshots` API or the corresponding CLI flags. Legacy in-memory
metrics remain accepted and are represented by deterministic synthetic lineage records.

The incumbent adaptive router remains the reference implementation. Any future policy
must reproduce its original branch on identical metrics before calibration results are
considered.

## MQL5 boundary

The production EA remains a separate execution product and is not coupled to this
research router. Its production preset is unchanged by this architecture pass. The
existing MQL5 `Core`, `Market`, `Decision`, `Risk`, `Execution`, `Analytics`, and `UI`
include tree is the intended long-term boundary for a future EA extraction; this pass
keeps the risk-sensitive v26.38 monolith behaviorally untouched rather than creating a
second, partially wired execution engine.
