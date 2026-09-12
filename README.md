# agentflow

An independent Python package for reproducible flow screens and few-channel
experiments. It includes an editable copy of FlowKit, a CLI for batch analyses,
and a Matplotlib desktop editor for human gate review.

**Version 0.7 is a team-evaluation release.** Default gates are draft drawing aids.
The example workflow is explicitly labelled **DUMMY / EXAMPLE — NOT VALIDATED**.
A real laboratory workflow still needs approved controls, detector assignments,
and gates. Unknown and unacquired channels are never silently fabricated.

## Open the desktop

```sh
uv sync --extra gui
uv run agentflow gui
```

Open an existing analysis folder or import FCS files. The Analysis menu saves,
opens analyses, and runs the loaded sample set to a new report directory. Source
FCS files remain unchanged. Recipes support JSON or YAML; sample sheets are CSV.
Review all draft gates before interpreting results.

## Start with the complete synthetic example

```sh
uv sync --extra gui
uv run agentflow demo --out local-examples/synthetic
uv run agentflow edit local-examples/synthetic/sample-1.fcs \
  --recipe local-examples/synthetic/workflow/recipe.json
uv run agentflow run local-examples/synthetic/workflow/samples.csv \
  --recipe local-examples/synthetic/workflow/recipe.json \
  --out local-examples/synthetic/run-01
```

Open `local-examples/synthetic/run-01/report.html` for the results. The example
contains three screen samples and four single-stain controls generated from known
signals/spillover. It exercises **FSC/SSC → singlets → live → GFP, mScarlet, Cy5**.
The fluorescence gates are parallel children of live cells, not a serial chain.

The desktop workbench uses **Manrope and Playfair Display**, native Qt controls
and Matplotlib plots. Open a screen with:

```bash
agentflow edit --samples local-examples/synthetic/workflow/samples.csv \
  --recipe local-examples/synthetic/workflow/recipe.json --gate live
```

See several populations at once in the clickable gallery, compare samples with
common axes, or click a plate well to select its sample. The main plot supports
scatter, density, contours and group-colored overlays. Detector names stay visible;
the Detectors dialog lists acquired detectors, marker annotations and dye roles.
Point size, opacity, scroll zoom and larger gate handles improve direct editing.
Histogram threshold fields use signal units matching the axes. Display previews
include linear/asinh/logicle; gate counts remain unchanged by view settings.

**Review & next**, undo/redo, and **Save & close** work across the shared recipe.
Close prompts for unsaved gate edits; external recipe changes are never overwritten.
The synthetic demo includes a clearly labelled dummy live/dead population on BV1-A.

[Screen workflow, sample-sheet schema, plotting behavior and plate summaries](docs/screen-workflow.md)
include reproducible commands and current limitations.

For headless analysis, `uv sync` omits Qt. On minimal Linux installations, the
desktop extra also needs the system libraries `libegl1`, `libopengl0`, and
`libxkbcommon0` (Ubuntu package names). Python 3.11+ is required. Distribution:
`agentflow-cytometry`; import and command: `agentflow`. This is not published on
PyPI and is independent of unrelated packages named AgentFlow.

## Use your own FCS file

Inspect the **PnN detector names**, marker labels, and embedded compensation first:

```sh
uv run agentflow inspect sample.fcs
uv run agentflow init sample.fcs --out local-examples/my-dummy --example \
  --compensation fcs --gfp BL1-A --mscarlet YL2-A
uv run agentflow edit sample.fcs --recipe local-examples/my-dummy/recipe.json
uv run agentflow run local-examples/my-dummy/samples.csv \
  --recipe local-examples/my-dummy/recipe.json --out runs/review-01
```

Only assign detector names that correspond to your actual dyes. The BL1/YL2 names
above are examples, not universal dye assignments. Add `--live DETECTOR` and
`--cy5 DETECTOR` only when those dyes were acquired. Otherwise their panels remain
unmapped and their populations are not analyzed. An identity FCS matrix is
reported as applying no spillover correction; it is not proof compensation was
properly calibrated. With no embedded matrix, choose `--compensation none`
explicitly, or supply `--matrix compensation.json`.

The downloaded-file walkthrough is in [docs/dummy-example.md](docs/dummy-example.md).
The original FCS file is read in place; neither it nor its derived outputs belongs
in Git. `local-examples/`, `runs/`, and FCS files are ignored.

## Screens and reproducible reruns

A CSV sample sheet requires unique `sample_id` and `fcs_path` columns. Relative
paths resolve from the CSV's directory. Other columns (plate, well, condition,
dose, replicate) appear in results with a `metadata:` prefix. Each sample runs
sequentially to bound memory use. Reuse the same recipe for every sample and rerun
into a new output directory after edits.

A completed run contains:

- `report.html`: local report linking results, gate-review figures and time QC.
- `summary.csv`: counts, percentages of parent/total, median signals, metadata,
  example labels and review flags. All counts use **all events**. Medians precede
  display transforms, using compensated signals unless mode is `none`.
- `gates-NNNN.png` and, when Time exists, `time-NNNN.png`: descriptive diagnostics.
  Saturation/upper-range counts are recorded, not automatically excluded.
- `recipe.json`, `samples.csv`, `run.json`: input fingerprints, resolved matrices,
  software versions and vendored-engine fingerprint, pending channels, and QC.

No sample is silently skipped. Empty parents yield zero counts and missing
percentages rather than division errors. Runs publish only after all samples
succeed and never intentionally overwrite existing output directories. Use
distinct directories for concurrent runs. Keep immutable inputs available;
fingerprints identify data but do not archive it.

## Compensation

FlowKit applies compensation; our separate module also imports labelled matrices
and estimates them from explicitly selected single-stain positive/negative
populations. This implementation does not require or copy Cytoflow.

```sh
uv run agentflow compensation import matrix.csv --out compensation.json
uv run agentflow compensation estimate controls.json --out estimated.json
```

CSV/TSV matrices need both row and column labels in identical order. Matrix rows
are source dyes and columns receiving detectors: `measured = true @ spillover`.
Use fractions, diagonal 1, and a **spillover matrix**, not its inverse. JSON stores
`mode`, `detectors`, and `values`. Singular/ill-conditioned matrices are rejected.

The synthetic example generates a complete `controls.json` demonstrating this
format. Estimation uses raw, untransformed signals and calculates
`(positive median - negative median) in target / same difference in source`.
Thresholds must identify matching positive and negative populations in each
single-stain tube; they are not inferred from the experimental samples. At least
50 events in each are required by default. Use correct particle backgrounds,
bright unsaturated controls, and an optional uncompensated cleanup recipe.
The output contains thresholds, median values, counts, and control fingerprints,
plus coefficient and before/after control plots. Inspect these before use; this
is not a claim of equivalence to FlowJo AutoSpill or Cytoflow's regression estimator.
The desktop **Calculate compensation…** dialog lets you assign single-stain files,
inspect histograms and adjust raw-signal thresholds. It exports the same estimator
results with control evidence and before/after plots. See [compensation details](docs/compensation.md).

Load a matrix into a recipe with `init --matrix`, by editing its `compensation`
object, or via the editor's **View / change matrix… → Import matrix…** controls. Loading
compensation invalidates all gate review flags. It does not silently move old
vertices to a new signal space.

## Recipes and Python API

See [recipe reference](docs/recipes.md) and [architecture](docs/architecture.md).
Recipes are JSON or YAML and work well in Git. All transforms have fixed parameters;
rectangles, polygons, and one-dimensional ranges compile into FlowKit's native
hierarchy. No independent GUI gating math is used.

```python
from agentflow import analyze_sample, load_recipe
from agentflow.batch import run_batch

recipe = load_recipe("recipe.json")
stats = analyze_sample("sample.fcs", recipe)
run_batch("samples.csv", "recipe.json", "runs/new-run")
```

To use from deliverome-analysis, install a reviewed commit:

```sh
uv add 'agentflow-cytometry @ git+https://github.com/Deliverome-Project/agentflow.git@<commit-sha>'
```

The private repository requires GitHub access. Replace `<commit-sha>` with the
reviewed revision; nothing needs copying into deliverome-analysis.

Every desktop save also writes `<recipe-name>.reproducibility.yaml` with the
complete recipe, Agentflow version, source fingerprint, dependency versions, and
Git commit and dirty status when running from a checkout. VCS installations record
their installation commit. An ordinary wheel without VCS metadata reports a null
commit (never a guessed one); its version and source fingerprint remain recorded.
A dirty checkout requires retaining its source changes as well as the commit.
Keep the snapshot beside the recipe: it is a generated export and is replaced
on the next save. To edit it independently, copy it to a separate recipe file.

Batch runs write `reproducibility.yaml` alongside `run.json`, including input
hashes and resolved compensation. These snapshots can be replayed directly:

```sh
agentflow run samples.csv --recipe runs/previous/reproducibility.yaml --out runs/replay
```

Snapshots do not bundle FCS inputs or install the recorded environment. Retain
the data and sample sheet, pin Agentflow to its recorded commit, and commit the
consumer project's `uv.lock` for a reproducible installation.

`agentflow validate recipe.json` checks a recipe. `agentflow export-gml sample.fcs
--recipe recipe.json --out gates.xml` exports gates, transforms, and resolved
compensation. Application notes, example labels and review flags are not part of
GatingML; preserve the JSON as the complete agentflow record. Recipes with sample
exceptions require `--sample-id ID` or `--shared-template` when exporting. Agents can use all
CLI commands except the optional desktop editor without a display.

## Development and ownership

```sh
uv run ruff check .
uv run pytest -q
uv build
```

Tests cover known compensation, reordered channels, hierarchy and range boundaries,
GatingML, batch replay/failures, editor save/cancel/undo/review behavior, unknown
roles, and the synthetic multi-channel workflow. Numerical agreement with your
approved laboratory analysis still needs a real-data comparison.

FlowKit 1.3.2 lives at `src/agentflow/_vendor/flowkit` with its BSD license and
upstream provenance. Import through `from agentflow import flowkit`; the upstream
package is not installed. Its three XSD schemas retain separate ISAC terms and
are preserved byte-for-byte. FlowIO, FlowUtils and other scientific dependencies
remain external and locked. See [third-party notices](THIRD_PARTY_NOTICES.md).

See [the roadmap](docs/roadmap.md) for prioritized FlowJo-style features; this
release does not claim a complete FlowJo replacement.

The [workspace feature design](docs/design/flowjo-workflows.md) translates the
FlowJo basic tutorial into proposed simpler workflows and shared GUI, CLI, Python
and YAML interfaces. It distinguishes current functionality from planned work.

See [saved analyses and metadata](docs/saved-analysis.md) for recipe versus snapshot
files, review status, instrument provenance, histogram defaults and reporter ratios.

### Sample summaries and default axes

New reporter/viability assignments use **logicle** (T from the detector's FCS range,
W=0.5, M=4.5, A=0); these are editable starting parameters, not fitted controls.
Existing recipes retain their explicit transforms and gate coordinates.

The multi-sample viewer defaults to **Sample MFI**: choose a population, detector,
and arithmetic mean or median. It calculates signal before display transforms,
after the recipe's compensation if present. MFI here means arithmetic mean,
not FlowJo's graph-space geometric mean. Bars retain individual samples (no
replicate averaging or inferred error bars), use `condition` labels and `group`
colors from the sample sheet, and can be clicked to select a sample. Notion-derived
annotations enter through the existing sample-sheet import; the viewer does not
query Notion or guess biological identities. Export the same table headlessly:

```bash
agentflow sample-summary samples.csv --recipe gates.yaml --population live \
  --detector FL5-A --statistic mean --out sample-summary.csv
```

Plate maps need explicit `plate` and `well` columns. Missing assignments are
explained in the viewer; filename suffixes are never assumed to be culture wells.
FSC/SSC views initially show the central 99% plus margin to prevent rare extreme
events from compressing the cells. **Plot settings → Full scatter range** restores
all events. This is a display crop only: every event remains in gate calculations
and exports. The selected summary and scatter-view settings are saved with YAML.
