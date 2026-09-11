# Agentflow's FlowKit copy

Imported from upstream FlowKit tag 1.3.2, commit
`f2159043b6a56e527d4baacf97490caf8354618e`. This directory contains the complete
`src/flowkit` runtime tree and upstream LICENSE, not upstream Git history,
test datasets, or documentation. Original per-file checksums are in UPSTREAM.json.

Local changes at import:

- Move the package under `agentflow._vendor.flowkit` to avoid shadowing upstream.
- In `_resources/__init__.py`, resolve the XML schemas using `__package__` so
  GatingML loads from this vendored package rather than a top-level `flowkit`.
- Add LICENSE, UPSTREAM.json and this maintenance note.

Public access is
`from agentflow import flowkit`. Keep the upstream version string unchanged;
Agentflow's run record also fingerprints vendored Python and XSD content to
identify our actual engine implementation.

When customizing: update this log, preserve upstream notices, and add scientific
regression tests. Do not run bulk formatting on upstream code. Review upstream
changes against the recorded commit; imports should be deliberate commits, never
an automatic replacement of this tree. Copy and review relevant upstream tests
and fixtures before changing an algorithm. Do not imply upstream authors endorse
our modifications. Build and test the wheel after resource or namespace changes.

The three XSD schemas have their own embedded ISAC terms (read-only usage and
free-of-charge distribution; modification reserved). Preserve them byte-for-byte,
including whitespace and embedded notices. They are standards resources, not
part of our freely editable Python implementation.

## Ratio support correction (2026-09-10)

- RatioTransform.apply accepts an optional pre-compensated event array, preserving
  the original raw-sample default. Division by zero retains IEEE nonfinite results.
- GatingStrategy honors RatioDimension.compensation_ref before taking the ratio,
  preserves a column per ratio when multiple derived dimensions are present, and
  copies compensated cache data before channel transformations mutate it.
- Agentflow compiles ratios into native RectangleGate + RatioDimension and a
  denominator floor, enabling standard Gating-ML serialization and parsing.
- Reviewed upstream tests/transform_tests.py at the recorded upstream commit:
  ratio output remains a 1D ndarray and direct sample transforms remain unsupported.
  Independent tests/test_ratio.py covers compensated and raw ratios, zero/negative
  denominators, multiple ratios, cached channel transforms and Gating-ML round trips.
