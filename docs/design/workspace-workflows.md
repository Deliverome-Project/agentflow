# Agentflow workspace and screen workflow design

Status: proposed design, based on Agentflow 0.5.0. The new YAML schema, Python
objects and CLI commands below are interface proposals, not available commands.
Implementation update: the population tree, ancestry gallery, parent/sample navigation
and next-draft controls are implemented in 0.6.0. YAML workspaces, quadrants and
the remaining proposed interfaces below are still planned.

Existing JSON recipes and commands continue to work. This document defines the
next implementation slices and their acceptance criteria.

## Design decision

Build a saved analysis workspace connecting samples, gate templates, endpoints
and report layouts. Keep the native Manrope / Playfair Display interface, with
one primary workbench and progressive disclosure of advanced settings. Every
scientific GUI action must have an equivalent Python operation and CLI command,
and serialize to the same validated configuration.

The target is repeated few-channel experiments and screens: load a plate, review
controls, reuse gates, inspect exceptions, export the same endpoints and figures,
and rerun when inputs or gates change. Broad specialist cytometry platforms are
outside the first implementation scope.

## Workflow coverage and gaps

| Workflow | Agentflow 0.5.0 | Proposed experience |
|---|---|---|
| Import files/folders; organize overlapping groups | CSV input; one color/filter group per row | Drop folder or import sheet; searchable sample table; overlapping named collections |
| Inspect metadata, compensation and acquisition quality | Detector dialog, matrix view, time plots and basic flags | Sample inspector with explicit status text and clickable QC evidence |
| Navigate a parent/child gating hierarchy | Shared native gating; flat population list and gallery | Collapsible population tree, ancestry strip and double-click drill-down |
| Ellipse, polygon, range, quadrant and rectangle tools | Polygon, range, rectangle and AND/OR | Add orthogonal quadrants first; native ellipsoids later; spider quadrants deferred |
| Adjust scaling around zero and negative values | Fixed analysis transforms; alternate display previews | Per-detector display controls with editable asinh/logicle parameters and saved presets |
| Apply a template to a group; edit and synchronize exceptions | Whole-sheet shared gates plus sample exceptions | Explicit analysis sets, linked templates, scope preview and promote/reset exception actions |
| Configure statistics for named populations | Fixed counts, parent/total fractions and medians | Endpoint builder with population, signal space, detector and denominator |
| Save plot layouts, include ancestry, iterate and batch | Fixed QC report and galleries | Reusable report boards; iterate by sample/condition/plate; headless export |
| Style, order and offset overlays | Group colors, normalization and pinned references | Legend toggles, stable ordering, line styles, offset histograms and shared bin settings |
| Build named tables and heatmaps, export | Fixed summary CSV and screen tables | Endpoint table preview, column aliases, explicit heatmap ranges; CSV/Parquet/HTML |
| Save workspace, template or data archive; reconnect files | JSON recipe, CSV sheet, immutable run directory | Workspace YAML, portable templates, fingerprint-based relinking and explicit data bundles |
| Derived parameters and specialist platforms | Not exposed | Consider named ratios after denominator handling; defer kinetics, cell cycle, proliferation and embeddings |

## Main window and interaction model

Keep three top-level views: **Samples**, **Gates**, **Results**. The project name,
DUMMY / EXAMPLE status, save state and current analysis set stay visible throughout.
Advanced settings open in side panels instead of spawning several windows.

- Samples: sortable rows with sample ID, plate/well, condition, control role,
  panel, matrix, event count and review/QC status. A group is a filter or collection;
  changing a filter never silently changes edit scope. Show detector and stain names
  together, for example `GFP · BL1-A`; unconfirmed mappings remain visibly unconfirmed.
- Gates: a collapsible tree on the left, large editable plot in the center and
  selectable ancestry/comparison thumbnails on the right. The tree includes count,
  percentage with named denominator, and text badges such as Shared, Exception,
  Draft and Reviewed. Color remains available for biological group identity.
- Results: endpoint table and plate map beside a saved report board. Clicking a
  result opens the contributing sample/population. Export uses the saved layout;
  a report never depends on a particular window size or open tab.

Plot selection and population selection are separate: selecting an axis changes
what is viewed, not the gate's detector definition. A parent breadcrumb returns
to upstream populations. Selecting a boundary chooses that gate; double-clicking
inside the selected gate drills into its population. Overlapping gates get a
small population chooser. All these actions have keyboard-accessible alternatives.

Keep gate handles large in screen pixels at every zoom. Show draft geometry while
dragging; recompute exact counts on release and distinguish pending counts from
current counts. Cancel stale redraw jobs on sample changes. Preview subsampling
must never feed the analytical masks. Displayed density plots need an event-density
legend; contour levels must state their meaning. Offset histograms are a view mode,
not a change in normalization or event counts.

## Collections, analysis sets and gate ownership

Use three distinct concepts:

1. **Collections** organize or compare samples. Membership can be explicit or
   expressed through a small typed metadata filter. A sample may belong to many.
   Do not evaluate arbitrary Python expressions from a YAML filter.
2. **Analysis sets** assign a compatible panel and a linked gate template to an
   explicit selection of samples. Within an analysis profile, a sample must resolve
   to exactly one set. Overlap conflicts fail validation with the competing IDs;
   never choose whichever group happened to be processed last. Alternate analyses
   use named profiles and produce separately identified outputs.
3. **Sample exceptions** override permitted gate geometry/review fields within
   the selected analysis set. They inherit its hierarchy and transforms.

Display scope beside the edit controls: `Template: reporter-panel · 24 samples`
or `Sample exception: A03`. Before a template change is committed, show which
sample IDs and dependent populations change, including existing exceptions.
Normal edits to an explicitly selected scope do not need repeated confirmation.

Linked template changes preserve exception geometry but invalidate affected reviews.
**Promote exception to template** shows a before/after diff and target set. Other
exceptions remain intact by default; replacing them is a separately named bulk
operation. **Reset exception** restores inherited geometry and clears dependent
review state. No synchronization behavior is inferred from gate color.

Resolve membership before execution and record the resolved sample IDs in the run
manifest. A new file matching a collection filter changes the manifest and cache
key. Refer to gates by stable IDs; renaming a display label must not break children,
Boolean references, endpoints or report tiles.

## Workspace files and Python ownership

Use YAML for editable, declarative source; use Python for orchestration and custom
extensions. GUI saves modify configuration, not arbitrary user Python source.
Both enter the same validated model and native FlowKit execution path.

```text
example-screen/
  workspace.yaml          # sample manifest, analysis sets, linked files
  samples.csv             # sample_id, path, condition, plate, well, replicate, etc.
  panel.yaml              # exact detector identities and reviewed role mappings
  gates.yaml              # versioned gates and explicit analysis transforms
  exceptions.yaml         # analysis-set/sample/gate patches and review records
  endpoints.yaml          # named population statistics and screen endpoints
  reports.yaml            # saved views, overlays, layouts and export settings
  analyze.py              # optional user-owned Python runner
  runs/                   # ignored, immutable derived outputs
```

Input FCS files remain external or in an ignored data directory. All relative paths
resolve against the file declaring them. Preserve JSON recipe import/export. Add
YAML 1.2 parsing with duplicate-key rejection, finite-number checks, unknown-field
errors, bounded aliases and no executable tags. Preserve comments and stable key
ordering for GUI edits, and quote IDs such as `001` so they remain strings.

A save involving several config files must be transactional: lock against another
writer, verify source hashes, stage all changes, and commit a new workspace revision
atomically through a small revision index/journal with recovery. Each run records
both original source-file hashes and the fully resolved canonical configuration.
Analytical cache keys derive from semantic configuration; comment changes do not
force regating. Render keys additionally include display configuration and fonts.

The first YAML delivery should be a lossless JSON-recipe adapter; do not combine
that migration with a change in gate membership semantics. Later workspace schema
versions introduce stable IDs and analysis sets with explicit migration commands.
Old recipes receive one default analysis set; old sample exceptions migrate intact.
Reject unsupported future schema versions rather than guessing.

### Proposed YAML shape (illustrative, not accepted by v0.5.0)

```yaml
schema_version: 1
experiment:
  id: dummy-reporter-screen
  label: DUMMY / EXAMPLE
  is_example: true
samples: samples.csv
collections:
  test_wells:
    where: {field: control_role, op: eq, value: sample}
  references:
    sample_ids: [DUMMY-NEG, DUMMY-POS]
analysis_sets:
  reporter_panel:
    sample_ids: [DUMMY-NEG, DUMMY-POS, DUMMY-A01]
    panel: panel.yaml
    gates: gates.yaml
    compensation: {mode: matrix, path: compensation.json}
    exceptions: exceptions.yaml
endpoints: endpoints.yaml
reports: reports.yaml
```

A matching endpoint proposal:

```yaml
schema_version: 1
endpoints:
  - id: gfp_positive_pct_live
    label: GFP positive (% live)
    statistic: fraction
    population: gfp_positive
    denominator: live
    scale: percent
  - id: gfp_median_live
    label: GFP median in live cells
    statistic: median
    population: live
    detector: BL1-A
    signal_space: compensated
```

The IDs above must resolve to the selected analysis set's gate template. These
snippets describe interfaces, not a complete analysis or biological gate settings.

### Proposed CLI and Python interfaces (not implemented yet)

```sh
agentflow workspace init --samples samples.csv --out example-screen
agentflow workspace validate example-screen/workspace.yaml --json
agentflow edit --workspace example-screen/workspace.yaml --sample DUMMY-A01
agentflow run --workspace example-screen/workspace.yaml --out runs/run-002
agentflow gates set-range --workspace example-screen/workspace.yaml \
  --analysis-set reporter_panel --sample DUMMY-A01 --gate live \
  --upper 5000 --units signal --dry-run
agentflow config diff old/workspace.yaml example-screen/workspace.yaml --json
agentflow report --run runs/run-002 --layout screening-review --out reports/review-002
agentflow workspace relink example-screen/workspace.yaml --search /data/new-location --dry-run
```

`5000` is a dummy example, not a recommended threshold. `--units signal` converts
through the explicitly resolved analysis transform. Mutation commands support a
source revision/hash precondition; dry runs report affected samples, dependencies,
review invalidations and validation errors without writing files. CLI overrides
are recorded in run provenance and never silently rewrite workspace defaults.
GUI save returns structured saved/cancelled/conflict status for an invoking agent.

```python
# Proposed public API; not available in Agentflow 0.5.0.
from agentflow.workspace import Workspace

workspace = Workspace.load("workspace.yaml")
workspace.validate()
change = workspace.gates.set_range(
    analysis_set="reporter_panel", sample="DUMMY-A01", gate="live",
    upper=5000, units="signal",  # DUMMY threshold
)
print(change.describe())
workspace.save(expected_revision=workspace.revision)
run = workspace.run(output="runs/run-002")
run.report(layout="screening-review", output="reports/review-002")
```

One transaction layer serves Qt, Python and CLI. Agents can propose and execute
requested edits, but do not manufacture a human review: review records distinguish
agent-authored, human-reviewed and draft states and bind to the effective gate,
parent, compensation and transform hashes. A stale review cannot remain valid.

## Gate and transform additions

Orthogonal quadrants are the highest-value new geometry for GFP/mScarlet or
reporter/viability comparisons. A single interaction creates four named child
populations with linked X/Y thresholds. Implement through native FlowKit quadrant
support, with explicit boundary ownership and a conservation test: disjoint masks
whose union is the parent, including events exactly on either threshold. Native
ellipsoid support also exists in the vendored engine, but converting GUI handles
to center/covariance/distance parameters needs separate numerical and export tests.
Do not approximate ellipses with undocumented polygons. Spider quadrants are later.

Add per-detector display settings for asinh cofactor, logicle parameters and visible
range, with original signal units on axes and previews against pinned controls.
Distinguish these display settings from the analysis coordinate system. Changing a
preview must preserve every mask bit. Changing an analysis transform is a reviewed
migration: range/rectangle limits can be mapped through inverse/forward transforms;
nonlinear transformations bend polygon edges, so mapping only vertices is not exact.
Initially keep polygon geometry bound to its original transform and allow display
changes independently. An intentional re-gating action creates a new revision,
shows count differences and invalidates dependent reviews.

## Endpoints and report boards

The endpoint builder asks: **which population, which statistic, which detector or
denominator, and which signal space?** Show that definition beneath the human label.
Support count, percent of an explicitly selected ancestor, median, mean and defined
quantiles first. Define quantile interpolation and preserve it in the run manifest.
Report compensated signal statistics before display transformation. A requested
compensated endpoint fails if compensation is unavailable. An empty denominator
returns missing with a reason, not zero. Geometric means and CV require explicit
nonpositive/near-zero policies; never silently drop problematic events.

A report board is a structured grid of plot, ancestry, endpoint table, plate map
and text tiles. Each tile references stable population/endpoint IDs, channels,
normalization, scales and sample selection. Drag/reorder tiles; start with a
six-panel gating board and a screen overview rather than a blank drawing canvas.
Iteration order is explicit and can follow plate/well, sample ID or metadata.
Pinned controls, legend order, line styles and shared histogram bins are saved.

Render the same board from a run snapshot through the headless renderer to PNG,
PDF and self-contained HTML. Export tables as CSV/Parquet and formatted HTML;
Excel is a later adapter. Table heatmaps explicitly choose per-column or shared
scales, display missing values distinctly, and never modify the underlying values.
Report-only changes can reuse event masks; editing a gate cannot reuse stale stats.

## Screening additions

These extensions support repeated screening workflows:

- Control roles distinguish compensation single stains, unstained, FMO, biological
  negative and positive controls. Filename suggestions require explicit assignment.
  FMO controls inform gate placement; they are not substitutes for single stains.
- Review queue prioritizes missing channels/matrices, low denominator counts,
  acquisition interruptions, saturation, sample exceptions and unreviewed gates.
  Flags show measured evidence and thresholds; no opaque good/bad score.
- Time exclusions are explicit saved intervals upstream of downstream gates, with
  exclusion reasons and before/after counts. Suggestions never silently discard data.
- Endpoint QC, plate position, dose, compound and biological/technical replicate IDs
  travel into result tables. Replicate summaries must not accidentally aggregate
  distinct treatments or treat acquired events as independent experimental units.
- Preserve current explicit control normalization; add exclusion reasons and control
  adequacy summaries before statistical hit calling or dose-response models.
- Extend the compensation wizard with cleanup editing and separate negative-file
  support only after shared-engine tests and representative control validation.

## Portability and relinking

A workspace references data; a template omits sample-specific paths and exceptions;
a bundle optionally includes data. Do not claim WSP/ACS/WSPT compatibility merely
based only on conceptual similarity. Relinking scans candidate files and
matches recorded fingerprints, with detector/event metadata as supporting evidence.
A filename alone is insufficient. Report ambiguous or missing matches; require an
explicit mapping for changed input content and clear affected reviews. Bundles
include a manifest and checksums; template export keeps required detector/matrix
contracts and fails visibly when a new panel is incompatible.

## Delivery sequence and acceptance gates

| Slice | Deliverables | Required evidence |
|---|---|---|
| A: Config foundation | JSON/YAML adapter, schema, migrations, public load/save API, semantic diff | JSON ↔ YAML preserves canonical recipe and exact masks; unknown/duplicate keys rejected; concurrent save conflict and recovery tested; headless wheel remains Qt-free |
| B: Workspace and ownership | Sample inspector, collections, analysis sets, stable gate IDs, explicit promotion/reset | Overlap conflicts fail; group edits touch only resolved targets; renames preserve references; sample exceptions survive migration; GUI/CLI/Python produce identical masks |
| C: Gate review | Tree/ancestry navigation, quadrants, configurable display scales, review queue | Quadrant boundary conservation; display-only changes preserve masks; original units remain visible; draft/selected states have text cues; small-window and keyboard usability checks |
| D: Results | Endpoint definitions, table builder, report boards, batch iteration | Denominator and empty-population tests; saved board reproduces headlessly; every displayed endpoint traces to its definition and input hashes; plot style changes do not regate |
| E: Screen reliability | Time exclusions, richer compensation cleanup, relinking, templates/bundles | Known synthetic exclusions/controls; missing and ambiguous file cases; representative lab comparisons with documented tolerances before claiming scientific parity |

A and the ancestry/quadrant portion of C are the recommended next implementation
work. B must precede group-scoped bulk operations. D relies on stable IDs and the
workspace model. Benchmark preview responsiveness and batch throughput on fixed
small and larger synthetic screens; publish timings and memory use instead of
promising a sample-count capacity before measuring it.

The minimum end-to-end acceptance scenario is: import grouped dummy samples,
assign controls, create a reporter quadrant, adjust one sample exception, save and
close, rerun through CLI, reopen the same populations, and export a reusable
ancestry/report board with identical counts. A team scientist then reviews the
workflow on representative real controls and compares selected counts/endpoints
with an approved reference analysis.
