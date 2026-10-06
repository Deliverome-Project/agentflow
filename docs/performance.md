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
same synthetic FCS files. Times below exclude profiling overhead. The final batch
uses the new density-dot QC defaults; the earlier performance-only implementation
measured 108.25 s with its older plots. The final run also includes the verified
Tornado 6.5.9 and urllib3 2.8.0 security updates.

| Operation | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| Full 96-well run, including event export and every QC image | 304.05 s | 115.53 s | 2.63× faster, including final density-dot QC; four rendering workers |
| Unchanged plate signal summary | 16.66 s | 0.024 s | About 700× faster after the initial scan |
| First plate signal summary | 17.27 s | 21.62 s | Initial all-event computation is not eliminated |
| Plate summary after changing its relevant gate | 16.37 s | 21.13 s | Recalculation remains necessary; editor yields between samples |
| Full statistics for one well | 0.162 s | 0.114 s | Combined quantiles reduce repeated work |

Offscreen Qt measurements on the same 96-well fixture, with the final density-dot default:

| Editor action | Before | After |
| --- | ---: | ---: |
| Open and finish first comparison | 43.36 s | 20.76 s |
| Switch sample, including completed comparison redraw | 22.39 s | 0.62 s |
| Redraw unchanged view | 24.95 s | 0.46 s |
| Select another population | 23.80 s | 0.35 s |
| Gate edit handler returns control | 0.52 s | 0.29 s |
| Gate edit's whole-plate comparison finishes | 20.27 s | 18.18 s |
| Longest opening event-loop heartbeat gap | 23.77 s | 1.27 s |

The final sample-comparison gallery took 18.48 s for its first all-plate extent
calculation, 1.57 s to load the next four-sample page, and 0.75 s to redraw that
page. Extents remain cached when events are evicted, so paging no longer rereads
the entire plate.

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
trials or latency guarantees. Tests ran during part of the baseline batch and an isolated package smoke check
overlapped the start of the final summary scan, so
its exact speedup should be confirmed on Brenna's workstation. The reproducible
scripts allow the same measurements with different event counts and worker counts.

## Changes

- Keep exact per-population counts and signal summaries separately from the
  eight-sample event cache. Up to 4,096 small summary entries survive event
  eviction. Populate all populations for the requested detector while a sample
  is resident. Relevant ancestor and Boolean-reference geometry, compensation,
  transforms, file identity/change metadata and declared fingerprints form the
  cache keys. Display and review changes do not invalidate numerical results.
- Cache up to 4,096 compact sample plot extents independently of event arrays;
  file identity, effective gates, compensation, transforms, population, channels
  and full-range selection invalidate them. Comparison pages load only their
  visible samples once the extents are available.
- Prepare plate-map, MFI and sample-gallery comparisons incrementally in the Qt event loop,
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
approximating counts. Overlaying many samples and the first computation of comparison-gallery
limits remain more expensive than inspecting a single sample. Event cache
capacity is bounded by sample count, not bytes; very large FCS files can still
use substantial memory. Rendering workers add bounded additional resident samples.

For larger workloads, measure peak memory and event-export versus rendering time
before increasing worker count. Potential next steps are an explicit byte budget
for event caches and per-stage export profiling. Do not
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

On the final code, including the gate-usability update from main, density-dot
views, metadata labels and security fixes, `uv run ruff check .` passed and
`uv run pytest -q` passed the complete suite. Additional regressions cover
processed-sample progress and cooperative cancellation without partial publication.
Two Matplotlib tight-layout warnings occur in the small-window gallery test.
Regression coverage includes cache eviction and invalidation, Boolean
references, transforms, compensation-file changes, superseding pending GUI
work, public Parquet schema preservation, bounded metadata arrays, identical
serial/parallel outputs and atomic cleanup after a rendering-worker failure.
The final editor timings include the integrated gate-usability changes. Density
view and metadata tests additionally verify that detector identities and exact
counts remain independent of names, point caps and display axes.

## Responsiveness targets and production comparison

A speedup over this application's baseline is not evidence of parity with FlowJo.
No matched FlowJo benchmark on the same hardware, data, gates and output bundle
has been performed; no installation was found in the standard Applications folder.
The vendor performance documentation describes implementation choices, not a
comparable 96-well wall-clock guarantee.

[Nielsen Norman Group's response-time guidance](https://www.nngroup.com/articles/response-times-3-important-limits/)
places immediate feedback around 100 ms, uninterrupted navigation below one
second, and attention loss around ten seconds. Longer jobs need progress and
an interrupt option. [Google's INP guidance](https://web.dev/articles/inp)
uses 200 ms for good input-to-next-paint responsiveness and 500 ms for poor
responsiveness. INP is a browser field metric; our Qt offscreen timers are not
INP and do not measure physical display presentation.

The following are Agentflow engineering targets derived from that guidance,
not claims about a vendor's speed or a formal certification:

| Action | Target on the reference workload |
| --- | --- |
| Gate drag feedback | p95 preview render ≤100 ms; avoid recomputing the plate during dragging |
| Cached sample/population selection | p95 first useful plot render ≤200 ms, full focused/comparison update ≤500 ms |
| Uncached navigation / gallery page | Useful feedback immediately, plot within 1 s where feasible; show loading otherwise |
| First plate scan / changed-gate plate calculation | Background or cooperative work with progress, supersession/cancellation and no stale results presented as current |
| Full export / QC report | Background job with completed-sample progress and cancel; measure throughput separately from interaction latency |

Twenty warm trials per action on the same 96-well fixture yielded these p95
values. `scripts/benchmark_editor.py --repetitions 20` writes the raw trials,
median, p95 and maximum to `interactions.json`. The first-plot measure records
Matplotlib's `draw_event`, excluding the benchmark's deliberately forced final
canvas redraws used in the earlier complete-action timer.

| Warm action | First plot render p95 | Completed comparison p95 |
| --- | ---: | ---: |
| Switch between two cached samples | 188 ms | 396 ms |
| Redraw | 103 ms | 359 ms |
| Change population | 95 ms | 312 ms |
| Drag threshold preview | 74 ms | 74 ms |

These warm actions meet the stated offscreen targets in this run. This is a
small single-session distribution, not a stable population estimate. Cold
comparison paging still took 1.6–1.9 s, and the longest opening heartbeat gap
was 1.1–1.3 s: those remain gaps against the navigation target. Initial and edited
plate completion takes roughly 18–22 s. Batch runtime of 115.53 s is a measured
throughput result, not an industry-standard acceptance threshold.

[FlowJo's documented performance techniques](https://flowjo.com/docs/flowjo10/setting-your-preferences/tools/performance)
include separate sample and request caches, calculation engines and limited-event
fast previews. Agentflow now uses separate exact-result/display caches, bounded
parallel QC and display-only point caps. Further improvements should move long
per-sample computation off the UI thread and budget caches by bytes.
[Qt documents worker execution](https://doc.qt.io/qt-6/threads.html) as a way to
keep expensive work from freezing the interface; Qt/Matplotlib widgets must
continue to be updated on the GUI thread.

Batch execution now reports processed samples and offers cooperative cancellation.
The last sample's progress is followed by a distinct finishing stage; 100% is not
shown before report publication. Cancellation waits for the current sample and
bounded pending rendering jobs, closes the event writer and deletes staging.
It never publishes a partial run. A cancellation arriving after successful
publication is reported as completed, not as a cancelled/deleted result.

Before claiming production parity, repeat cold and warm trials across multiple
sessions on Brenna's workstation, measure native input-to-visible-feedback and
peak memory, and compare equivalent FlowJo workflows and outputs. Keep exact
count/value equality as a release condition; speed must not come from omitting
samples, weakening compensation or reducing analytical precision.
