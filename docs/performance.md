# Plate performance

Benchmarks use deterministic synthetic FCS files, not experimental event data.
The workload size comes from a read-only inspection of locally available FCS
headers from Brenna's September 24, 2026 experiments:

| Experiment | Files | Channels | Minimum events | Median events | Maximum events |
| --- | ---: | ---: | ---: | ---: | ---: |
| S4E1, FBS lot testing | 46 | 32 | 31,334 | 100,000 | 100,000 |
| S4E6, detachment methods | 15 | 32 | 67,708 | 100,000 | 100,000 |

Both had a 95th percentile of 100,000 events. The benchmark therefore uses
96 wells × 100,000 events × 32 acquired channels (9.6 million events), with an
explicit four-detector compensation matrix, four logicle transformations,
scatter/singlet gates, four reporter thresholds and one Boolean gate. Synthetic
gate boundaries are arbitrary workload fixtures, not biological thresholds.
Experimental data and analysis outputs are not included in this repository.
Agentflow does not depend on the repository where those headers were found.

## Reproduce

```sh
uv run python scripts/benchmark_plate.py --out /tmp/agentflow-plate-benchmark
uv run python scripts/benchmark_editor.py --input /tmp/agentflow-plate-benchmark \
  --out /tmp/agentflow-editor-benchmark
```

Use a new output directory each time. `--input` on the plate benchmark reuses an
existing synthetic fixture. `--workers 1` isolates serial behavior;
`--workers 4` matches the CLI/desktop default. `--profile` writes a cumulative
CPU profile, but changes timing and does not profile child rendering processes.
`--skip-batch` measures preparation, gating, summary and QC latency without
writing the full event export. Fixture generation and application import time
are outside the timers. The editor benchmark includes Qt drawing offscreen;
it is not a measurement of physical display latency. It requires the GUI extra.

## Measured results

Measured October 5, 2026 on macOS 26.3.1, ARM64, eight logical CPUs, 16 GiB RAM,
Python 3.11.5. Baseline: dev commit `5cf360e`; optimized runs reused exactly the
same synthetic FCS files. Times below exclude profiling overhead.

| Operation | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| Full 96-well run, including event export and every QC image | 304.05 s | 108.25 s | 2.81× faster; serial baseline, four rendering workers after |
| Unchanged plate signal summary | 16.66 s | 0.020 s | About 850× faster after the initial scan |
| First plate signal summary | 17.27 s | 17.75 s | Initial all-event computation is not eliminated |
| Plate summary after changing its relevant gate | 16.37 s | 18.04 s | Recalculation remains necessary; editor yields between samples |
| Full statistics for one well | 0.162 s | 0.112 s | Combined quantiles reduce repeated work |

Offscreen Qt measurements on the same 96-well fixture:

| Editor action | Before | After |
| --- | ---: | ---: |
| Open and finish first comparison | 43.36 s | 19.23 s |
| Switch sample, including completed comparison redraw | 22.39 s | 0.44 s |
| Redraw unchanged view | 24.95 s | 0.25 s |
| Select another population | 23.80 s | 0.14 s |
| Gate edit handler returns control | 0.52 s | 0.21 s |
| Gate edit's whole-plate comparison finishes | 20.27 s | 19.66 s |
| Longest opening event-loop heartbeat gap | 23.77 s | 0.90 s |

The heartbeat includes initial construction and rendering, and samples every
20 ms. It shows reduced blocking, not a guaranteed frame rate. A gate edit still
needs a fresh plate calculation; the immediate focused-sample update and final
whole-plate completion are intentionally reported separately.

The small initial profiling workload (96 × 10,000 events × eight channels)
spent 63.35 of 78.03 profiled seconds inside gate/time QC rendering. At the full
workload size, repeated instrument metadata also caused substantial allocation
and memory pressure. An intermediate implementation that still materialized
those strings was stopped; it is not included in the after timings.

These are individual runs on an active workstation, not isolated repeated
trials or latency guarantees. Tests ran during part of the baseline batch, so
its exact speedup should be confirmed on Brenna's workstation. The reproducible
scripts allow the same measurements with different event counts and worker counts.

## Changes

- Keep exact per-population counts and signal summaries separately from the
  eight-sample event cache. Up to 4,096 small summary entries survive event
  eviction. Populate all populations for the requested detector while a sample
  is resident. Relevant ancestor and Boolean-reference geometry, compensation,
  transforms, file identity/change metadata and declared fingerprints form the
  cache keys. Display and review changes do not invalidate numerical results.
- Prepare plate-map and MFI comparisons incrementally in the Qt event loop,
  yielding after approximately 30 ms or one expensive sample. A newer request
  cancels unfinished work; old plots are cleared while preparing. A single large
  sample can still take longer than 30 ms. No partial plate is presented as a
  completed comparison and sample errors remain visible.
- Reuse the active editor's masks between its plot and count refresh.
- Use affine axes when data already uses the recipe scale. Keep the detector
  tick labels in signal units and retain nonlinear transformations for alternate
  display scales. This follows [Matplotlib's advice to use backend affine
  transformations where possible](https://matplotlib.org/stable/api/transformations.html).
- Calculate the four requested percentiles together using
  [NumPy's multiple-quantile API](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html),
  and reuse population counts. Median, finite-event handling and sample SD retain
  their definitions.
- Dictionary-encode constant event metadata before writing, avoiding allocation
  of a full instrument-JSON string for every event. Use the
  [Parquet writer’s schema and metadata controls](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html)
  to preserve ordinary string columns on read, rather than exposing categorical
  types. The event schema, all raw and
  compensated float64 values, original event indices and fingerprints stay intact.
- Render QC in isolated processes, with at most one pending sample per worker.
  The CLI and desktop use four workers; `--workers 1` reduces memory demand.
  The Python `run_batch` API defaults to one worker; callers can opt into
  parallel rendering with `workers=4` and should use a `__main__` guard in scripts.
  Failures in a rendering worker abort publication and clean the staging folder.
  Event export stays ordered and streaming; no whole-plate event concatenation
  or parallel Matplotlib threads are used.

## Limits and follow-up

The first view of a plate and changes that affect its selected population still
require all-event analysis. Caching accelerates repeated inspection rather than
approximating counts. Overlaying many samples and computing comparison-gallery
limits remain more expensive than inspecting a single sample. Event cache
capacity is bounded by sample count, not bytes; very large FCS files can still
use substantial memory. Rendering workers add bounded additional resident samples.

For larger workloads, measure peak memory and event-export versus rendering time
before increasing worker count. Potential next steps are an explicit byte budget
for event caches, cached comparison extents, and per-stage export profiling. Do not
silently drop QC, omit events, reduce numeric precision, or change compensation
to achieve a faster benchmark.

These are performance and synthetic regression checks. They do not establish
biological validity or equivalence to an experimenter's real-data gating workflow.

## Correctness checks

The before/after full-size runs have exactly matching summary and quality CSVs,
all 96 Gating-ML files, input fingerprints, resolved compensation and acquisition
metadata. A streaming comparison verified every field in all 9,600,000 event
rows, including raw and compensated detector values, original indices and all
gate memberships. Implementation provenance appropriately changes between runs.

After integrating the concurrent gate-usability update from main,
`uv run ruff check .` passed and `uv run pytest -q` passed all 126 tests.
Two Matplotlib tight-layout warnings occur in the small-window gallery test.
Regression coverage includes cache eviction and invalidation, Boolean
references, transforms, compensation-file changes, superseding pending GUI
work, public Parquet schema preservation, bounded metadata arrays, identical
serial/parallel outputs and atomic cleanup after a rendering-worker failure.
The recorded editor timings precede that gate-usability integration; the
numerical and batch-processing changes are unchanged by the integration.
