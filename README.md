# Agentflow

Agentflow is a Python toolkit for reproducible flow cytometry analysis, with a
command-line interface and an optional desktop gate editor. It is designed for
scientists running repeated experiments and screens, especially panels with a
few fluorescence channels and straightforward gating.

Define samples and conditions in a CSV sample sheet, review gates visually, and
save the analysis as YAML or JSON. The same configuration can be rerun from the
command line or Python, including by coding agents. A bundled, modified copy of
[FlowKit](https://github.com/whitews/FlowKit) provides the analysis engine.

> **Active development — early evaluation release.** Interfaces, configuration
> formats and workflows may change. Pin a commit for reproducible work. Generated
> gates are starting points for human review, and synthetic tests do not establish
> validation for your instrument, controls or assay.

## What you can do

- Review hierarchical polygon, rectangle, histogram, Boolean and reporter-ratio
  gates in a Qt/Matplotlib desktop interface.
- Apply shared gates across samples, with explicit sample-specific exceptions.
- Compare samples using scatter, density, contour and histogram plots, group
  colors, and mean or median fluorescence summaries.
- Apply embedded or imported compensation matrices, or estimate spillover from
  user-defined single-stain control populations.
- Run batches without a display, export per-event Parquet and summary CSV, and
  exchange supported gate definitions through Gating-ML.
- Preserve gate settings, input fingerprints, reported instrument metadata and
  software provenance for review and reruns.

## Installation

Python **3.11 or newer** and [uv](https://docs.astral.sh/uv/) are required for the
source-checkout instructions below. The distribution is `agentflow-cytometry`;
the Python import and executable are `agentflow`. It is not currently published
on PyPI and is unrelated to other packages named AgentFlow.

```sh
git clone https://github.com/Deliverome-Project/agentflow.git
cd agentflow
uv sync
```

This installs the headless analysis tools. For the desktop editor:

```sh
uv sync --extra gui
uv run agentflow gui
```

The repository is currently private while public-release preparation is underway;
cloning requires access until its visibility changes. On minimal Ubuntu systems,
the desktop also needs `libegl1`, `libopengl0` and `libxkbcommon0`. Headless analysis
does not require Qt.

To use Agentflow in another Python project, pin a specific reviewed commit:

```sh
uv add 'agentflow-cytometry @ git+https://github.com/Deliverome-Project/agentflow.git@<commit-sha>'
```

Replace `<commit-sha>` with the full commit identifier and retain your lockfile.

## Try a synthetic experiment

The bundled demo generates three samples and four single-stain controls. All
files and suggested gates are labelled **DUMMY / EXAMPLE — NOT VALIDATED**; no
experimental data is needed.

```sh
uv run agentflow demo --out local-examples/synthetic
uv run agentflow run local-examples/synthetic/workflow/samples.csv \
  --recipe local-examples/synthetic/workflow/recipe.json \
  --out local-examples/synthetic/run-01
```

Open `local-examples/synthetic/run-01/report.html` to inspect the results. Keep the
report together with its generated figures and linked files.

With the desktop extra installed, edit the same experiment:

```sh
uv run agentflow edit --samples local-examples/synthetic/workflow/samples.csv \
  --recipe local-examples/synthetic/workflow/recipe.json --gate live
```

The example hierarchy is scatter → singlets → live cells, with GFP, mScarlet and
Cy5 populations as parallel children of live cells. The viability stain and
reporter assignments are synthetic examples, not recommended detector mappings.
Save your edits, then rerun into a new output directory such as `run-02`.

## Analyze your own experiment

Start with `uv run agentflow inspect sample.fcs` to examine acquired detector
names, marker labels and embedded compensation. Use the desktop import workflow
or the [CLI walkthrough](docs/dummy-example.md) to create a draft recipe, then
review detector assignments, controls and gate boundaries for your experiment.

A sample sheet requires unique `sample_id` and `fcs_path` columns. Paths may be
relative to the sheet. Add `condition` and `group` for meaningful plot labels and
colors; plate maps require explicit `plate` and `well` columns. Other annotations,
such as dose and replicate, are retained as metadata. See the
[sample-sheet and screen workflow guide](docs/screen-workflow.md).

```sh
uv run agentflow validate gates.yaml
uv run agentflow run samples.csv --recipe gates.yaml --out runs/experiment-01
```

Source FCS files are not modified. Counts use all events, regardless of plot
subsampling or zoom. Samples are processed sequentially to bound memory use;
missing channels and failed samples produce errors rather than silent omissions.
Completed runs use new output directories.

### Gates and display

New fluorescence assignments default to **logicle**, with the upper range taken
from the detector metadata. Scatter defaults to linear. Existing recipes retain
their explicit transforms; changing a display preview does not change gate
membership. Histogram gates default to bounded intervals.

The population gallery supports navigation between gates, and sample comparisons
use a fixed 2×2 grid. Fluorescence summaries show up to 30 samples per page and can
follow the selected population. Mean and median are computed before display
transforms, after compensation when applied. MFI means arithmetic mean here;
replicate averaging and error bars are not inferred automatically.

Editing a gate marks that gate reviewed; affected descendants need separate
review. Saving alone does not approve untouched draft gates. See
[saved analyses and review state](docs/saved-analysis.md) for details.

### Compensation

Choose an embedded FCS matrix, import a labelled spillover matrix, or calculate
one from explicitly selected positive and negative populations in single-stain
controls. Both CLI and desktop workflows are available:

```sh
uv run agentflow compensation import matrix.csv --out compensation.json
uv run agentflow compensation estimate controls.json --out estimated.json
```

The estimator uses differences in positive/negative medians; it is not a spectral
unmixing workflow. Inspect control quality and before/after plots before applying
a matrix. An identity matrix applies no correction and does not establish that
compensation is adequate. Changing compensation invalidates gate review flags.
See [control configuration and matrix conventions](docs/compensation.md) and
[current validation limits](docs/compensation-audit.md).

## Outputs and reproducibility

| Output | Contents |
|---|---|
| `report.html` and figures | Gate-review plots, result tables and acquisition QC |
| `summary.csv` | Population counts, percentages, signal statistics and sample metadata |
| `events.parquet` | Individual events, metadata and population membership |
| `gates-*.gatingml.xml` | Per-sample gates, transforms and resolved compensation |
| `reproducibility.yaml` | Replayable recipe with software and input provenance |
| `run.json`, `recipe.json`, `samples.csv` | Execution record and configuration snapshots |

Keep the original FCS inputs, sample sheet, recipe and pinned environment.
Snapshots identify inputs but do not bundle them or recreate the environment.
Reported instrument fields are recorded as metadata, not independently verified
calibration; missing values remain unknown. Inspect raw acquisition keywords for
personal or sample identifiers before sharing outputs.

Desktop saves also write a `*.reproducibility.yaml` snapshot. Git installations
record their installation commit; checkouts record commit and dirty status.
Retain uncommitted source changes if you run from a dirty checkout. Wheels without
Git metadata record a version and source fingerprint instead of inventing a commit.

## Python and agent workflows

```python
from agentflow import analyze_sample, load_recipe
from agentflow.batch import run_batch

recipe = load_recipe("gates.yaml")
statistics = analyze_sample("sample.fcs", recipe)
run_batch("samples.csv", "gates.yaml", "runs/new-run")
```

Agents can inspect inputs, prepare sample sheets, validate recipes and run batches
through the same Python and CLI interfaces used by people. The desktop editor is
optional; it provides human review of the saved configuration. Gating-ML exports
mathematical gate definitions, while the recipe retains application settings and
review annotations. See the [recipe reference](docs/recipes.md) and
[architecture](docs/architecture.md).

## Development

Bug reports and reproducible examples are welcome. Use synthetic or appropriately
shareable data, and include your version, command and error output. Current plans
are in the [roadmap](docs/roadmap.md) and
[workspace design](docs/design/workspace-workflows.md); proposed features there
are not necessarily implemented.

```sh
uv run ruff check .
uv run pytest -q
uv build
```

## Author and licensing

Agentflow is created and maintained by **Becca Carlson**, its sole listed project
author. This designation applies to Agentflow, not its bundled dependencies.
FlowKit retains Scott White's copyright and its accompanying BSD 3-Clause license.
Fonts and standard XML schemas retain their own terms and copyright holders.
No upstream endorsement is implied. See [third-party notices](THIRD_PARTY_NOTICES.md).

The proposed license for original Agentflow code is MIT. Public release is pending
the [release review](docs/release-review.md); this proposal does not relicense
bundled components or grant a new license to the original code yet.
