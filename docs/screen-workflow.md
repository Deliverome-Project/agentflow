# Multi-sample screening workflow

Agentflow keeps one shared gate recipe for the samples opened together. Color
classes are experimental groups; changing the color filter does not change which
samples receive the recipe. Use a separate recipe/sample sheet for incompatible
panels or a distinct gating strategy. Per-sample gate exceptions are not yet a
workspace feature. Explicit per-sample compensation matrices are supported.

## Inputs

```csv
sample_id,fcs_path,group,color,plate,well,biological_replicate,control_role,compensation_path
vehicle-1,data/vehicle.fcs,Vehicle,#3d6b60,P1,A01,1,negative,matrices/day1.csv
positive-1,data/positive.fcs,Positive,#922038,P1,A02,1,positive,matrices/day1.csv
treatment-1,data/treatment.fcs,Treatment,#5848a8,P1,A03,1,sample,matrices/day1.csv
```

`sample_id` and `fcs_path` are required. `group` falls back to `condition`, then
“All samples.” `color` is optional; assignments are deterministic and conflicts
within a group fail. File paths resolve relative to the sample sheet. All other
metadata is retained. `compensation_path`, when supplied, overrides the recipe's
matrix for that sample; otherwise the recipe's none/FCS/imported mode applies.
Resolved matrices, their source hashes, and per-sample signal spaces are recorded.

```bash
agentflow edit --samples samples.csv --recipe recipe.json
agentflow run samples.csv --recipe recipe.json --out runs/01 --cache .agentflow-cache
agentflow screen runs/01 --gate gfp --metric percent_parent --out screens/01
```

## Review in the desktop workbench

- Choose a sample, group filter and optional overlay. Sample selection keeps the
  same population selected; edits apply to the entire sample sheet.
- The **All populations** gallery shows the hierarchy simultaneously, with detector
  names and counts. Click a plot to edit that population. Gates sharing the same
  parent and detector pair also appear together on the main plot; click a boundary
  to select it. **New population** adds a range, rectangle, polygon or AND/OR
  combination of existing gates.
- **Compare samples** shows the selected population across samples with common
  limits. The gallery is paginated at twelve samples/populations to bound canvas
  size. **Plate map** shows one plate per page; click a populated well to select
  its sample. Percent, count and median of the gate's first detector are available.
- **Detectors** lists every acquired PnN detector, its PnS marker annotation and any
  assigned dye role. Unknown mappings remain labelled as candidates.
- **Scatter** uses visible points with adjustable size and opacity. Scroll zooms
  around the pointer. The display uses a deterministic maximum of 20,000 points
  per sample; population counts always use all events.
- **Density** is a log-count hexbin plot using all parent events. In group overlays,
  density becomes colored contours so colors identify groups. Contours are levels
  at 10/30/60/85% of each smoothed density peak, not probability-content contours.
- One detector produces a histogram. Overlay bins are common across samples.
  Counts, unit area and percent-of-peak normalization are available. Each sample
  is normalized independently, avoiding event-count weighting of replicate curves.
- Axis tick labels and threshold entry use uncompensated/compensated **signal
  units**, not internal transformed coordinates. Recipes continue to store exact
  gating coordinates; rounded field text does not round an unchanged threshold.
- Linear, asinh and logicle display previews preserve gate counts. Ranges and
  rectangles can be adjusted in these monotonic display views. Polygons are
  editable on their recipe axes; alternative polygon views are inspection-only
  because transforming a polygon's vertices alone changes curved-edge semantics.
  **Use gating axes** restores editing. Preview asinh uses cofactor 150; preview
  logicle uses T=262144, W=0.5, M=4.5, A=0. Actual analysis transformations and their
  explicit parameters remain in the recipe. Histogram binning/normalization remains
  in recipe coordinates during an alternate-axis preview.
- Save stores plot preferences as well as gates; batch QC figures use these
  preferences. Close offers Save/Discard/Cancel for gate changes. Display-only
  preferences are saved when Save is selected.

Sample preparation uses a bounded in-memory cache. Optional `--cache` reuses a
complete identical headless run, keyed by input/recipe/matrix contents, implementation,
font assets and dependency versions. Cached artifacts are verified before reuse;
new runs still use new output directories. Changed recipes invalidate the run cache.
This is whole-run reuse, not a promise of partial per-gate disk recomputation.

## Plate summaries and hit review

`screen` produces `wells.csv`, `plates.csv`, `replicates.csv`, plate PNGs when well
positions are provided, and `screen.json` recording parameters and input hash.
Each plate is normalized as:

```
100 * (sample value - negative-control median)
    / (positive-control median - negative-control median)
```

Missing or indistinguishable controls yield missing normalized values. Z-prime
uses control means and sample standard deviations and is omitted with fewer than
two eligible wells per control class. There is no default hit cutoff; optional
`--hit-threshold` selects sample wells at/above an explicitly chosen percent-control
threshold. All results remain draft.

`--min-events` defaults to 100 as a configurable software QC threshold, not a
universal assay rule. For median signal endpoints it checks the gated population;
for count/percentage endpoints it checks parent event count, so a negative control
with zero positive events is not incorrectly rejected. This endpoint QC does not
replace reviewing compensation, acquisition and detector-range diagnostics in
`quality.csv`. Replicate summaries describe eligible wells within plate/group and
biological replicate when provided. They do not treat individual cells as independent
replicates, perform significance tests, or merge biological replicates silently.

Use separate `screen` calls for reporter expression, percent positive and viability.
Control definitions, meaningful effect sizes, toxic-well exclusions, batch correction,
dose-response fitting and statistical hit criteria require assay-specific decisions.

## Dummy live/dead playground

```bash
agentflow demo --out local-examples/screen-playground
agentflow edit --samples local-examples/screen-playground/workflow/samples.csv \
  --recipe local-examples/screen-playground/workflow/recipe.json --gate live
```

This generates three samples and four single-stain controls. All are synthetic.
Dummy viability is assigned to BV1-A; GFP to BL1-A; mScarlet to YL2-A; Cy5 to RL1-A.
The known simulated signal distributions use a dummy 5000-unit threshold for
interaction practice. The downloaded Attune file is not modified or assigned a
fictional measured viability channel.

## Design references

The group/gallery workflow is informed by [FlowJo's analysis tree](https://flowjo.com/docs/flowjo11/analysis-tree-2)
and [graph gallery](https://www.flowjo.com/docs/flowjo11/graphs-and-gating).
See [FlowJo transforms](https://flowjo.com/docs/flowjo11/graphs-and-gating/transforms)
for display-scale context and this [flow screening protocol](https://pubmed.ncbi.nlm.nih.gov/33778785/)
for control-based gating and expression/viability plate summaries. Agentflow does
not claim exact implementation equivalence to FlowJo or Sony software.

## Pinned reference samples

Choose **Pinned controls…** to keep one or more named samples overlaid while
stepping through test samples or filtering groups. Pinning does not pool events,
change gates or assign experimental control roles. Pinned traces retain their
group colors and have sample-specific legend labels. The active sample always
remains visible. Pin selections are saved in `display.pinned_samples` and support
undo/redo. The plate and comparison galleries continue to follow the group filter.

## Sample-specific gate exceptions

**Edit gates for → All samples** changes the shared template. **This sample only**
stores geometry and review exceptions under the selected sample's exact
`sample_id`. Counts and gallery boundaries use the effective gates for each sample;
CLI runs apply the same exceptions. The hierarchy, channels and transforms remain
shared. Newly created populations and compensation changes are shared operations.

A sample exception stays in place when shared gates change. Changes to a parent,
Boolean dependency or compensation invalidate affected review flags, including
sample-specific reviews. A gate with different sample geometry is read-only in
All samples mode: switch to This sample only, or choose **Reset selected exception**.
Reset restores shared geometry and marks the affected sample populations for review.
Geometry and review changes are saved together, with undo/redo and protection
against overwriting a recipe changed by another process. Per-sample exceptions are
also recorded in `run.json` alongside each input.

```json
"sample_overrides": {
  "sample-001": {
    "live": {"bounds": [null, 4.0], "reviewed": false}
  }
}
```

Recipe coordinates remain transformed coordinates; GUI threshold fields use signal
units. Sample IDs are exact identifiers, not filenames. Reusing an ID for unrelated
data also reuses its exceptions: keep IDs stable and unique across a study.

## Interactive compensation calculation

Choose **Calculate compensation…**. Assign each detector's single-stain FCS file,
or load an existing control configuration. Select a row to view its histogram;
click to place the negative maximum or positive minimum, or type exact raw values.
The two populations must be nonoverlapping and sufficiently populated. The graph
uses an asinh display to retain negative/near-zero signals; thresholds stay in raw units.

**Calculate & export review…** creates a new folder containing the exact control
configuration, draft matrix with hashes/counts/medians, matrix image and before/after
control plots. Failed calculations publish no partial folder. Inspect the diagnostic
plots before choosing **Apply draft matrix**; applying invalidates gate reviews.
Sample-sheet `compensation_path` assignments still take precedence over the shared
matrix. The original sample files are never modified.

To practice, load the synthetic demo's `controls.json`. The example has four
single-stain files and known spillover. The estimator uses the same-file median
method described in [compensation controls](compensation.md), including its
limitations. A configured uncompensated cleanup recipe is supported and its eligible
events appear in the preview. Drawing cleanup gates inside this dialog and separate
unstained negative files are not implemented yet.

## Population hierarchy and guided review

The left sidebar is a collapsible tree reflecting actual parent/child gates.
Selecting a nested population expands its ancestors. Hover a row for detector names,
its denominator and percentage, and shared/exception review details. Renaming or
creating populations continues to use the saved recipe; the tree is a view of it.

Choose **Ancestry** in the gallery to show the selected population and its upstream
chain in order. Click a thumbnail to select that population, or **↑ Parent** to
move upstream. Boolean populations show their parent chain; their additional logical
references are not represented as extra ancestry branches.

The **‹ / ›** sample buttons follow the selected comparison group without wrapping
at its ends. They preserve pending valid threshold edits before switching; invalid
thresholds block navigation. **Next draft →** skips reviewed populations in the
current sample and cycles to the next draft or unassigned role. It does not mark
anything reviewed automatically. Use **Review & next** when approving a gate.

**Focus plot** hides the right-hand gallery to give the editable plot more room.
Turn it off to restore the gallery. The focus setting and gallery mode are saved
with other display preferences; neither changes population membership.

## Open, import, save and rerun in the desktop

Start with `agentflow gui`. **Open analysis folder** loads `recipe.json` and
`samples.csv`; **Choose recipe and sample sheet** supports files stored separately.
The launcher checks referenced FCS paths and reports errors before opening the
editor. This is a JSON recipe/sample-sheet workflow, not the proposed YAML
workspace implementation.

**Import FCS files** creates a new analysis folder without copying or changing the
source FCS files. Choose a new folder name and explicitly select embedded
compensation or uncompensated analysis. Duplicate sample stems and incompatible
inputs fail without publishing a partial analysis folder. Draft scatter and
singlet gates use the first sample; review them across the full sample set and
assign fluorescence detectors explicitly after opening. Import currently requires
FSC-A and SSC-A. Use the sample sheet for group colors, plate/well and control roles.

Inside the workbench, the **Analysis** menu opens another analysis, saves without
closing, or saves and runs all samples. **Save and run all samples** writes the
current recipe, asks for a results location, and creates a new `run-NNN` directory.
The existing CLI executes in a separate process; edits are disabled while it runs.
The generated HTML report opens when complete. Failures restore the editor and
show the error. Runs cannot currently be cancelled in the GUI. The exported
`samples.csv` captures the loaded sample metadata; changes to the original sheet
require reopening the analysis.

Later edits after saving become unsaved again and trigger the normal close prompt.
**Save & close** remains available. The analysis folder can be reopened through
the launcher, and the same recipe/sample sheet can be rerun through the CLI.

Plot appearance settings are collapsed by default, and the central panel scrolls
when needed so plots retain readable axes. Narrow galleries use one column.
**New population** defaults to a child of the selected population; choose Sibling
or Choose parent explicitly for another relationship. New populations are shared
recipe operations even when sample-only geometry editing is selected.

After calculating compensation, **Review before / after** opens the exported
control diagnostics inside the app. Select a detector to switch controls; scroll
for the full-resolution image. Applying the draft matrix is still a separate action.
