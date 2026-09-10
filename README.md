# agentflow

Reproducible flow cytometry analysis for screens and experiments with a few channels.
Built on **FlowKit**, with a command-line interface, an importable Python API, and
an optional **Matplotlib** gate editor. Early prototype; validate gates and
compensation on representative experimental data before using its results.

## Install

From a checkout, install [uv](https://docs.astral.sh/uv/) and run:

```sh
uv sync --extra gui
uv run agentflow --help
```

For a server or agent running batch analyses, `uv sync` omits the Qt GUI dependency.
Python 3.11 or newer is required. The distribution is `agentflow-cytometry`; the
Python import and command are `agentflow`. This project is independent of other
projects named AgentFlow and is not published to PyPI.

## Try a complete synthetic screen

```sh
uv run python examples/make_demo.py
uv run agentflow inspect demo/sample-1.fcs
uv run agentflow run demo/samples.csv --recipe demo/recipe.json --out runs/demo-01
uv run agentflow edit demo/sample-1.fcs --recipe demo/recipe.json --gate positive
uv run agentflow run demo/samples.csv --recipe demo/recipe.json --out runs/demo-02
```

The editor shows the parent population, gate outline, and count across **all**
events. Drag rectangle handles or polygon vertices to adjust the gate. **Save &
Close** writes the recipe and returns success to the caller. Cancel or closing
with the window's close button leaves the recipe unchanged and returns exit code
2. Errors return 1. A recipe changed by another process is rejected at save time.
A desktop display is required only for `edit`.

To start from your own FCS file:

```sh
uv run agentflow edit sample.fcs --recipe gates.json --gate cells \
  --x FSC-A --y SSC-A --kind polygon --compensation none
```

A new gate starts as a suggested box covering the central 90% on each axis;
**this is a drawing aid, not an automatically validated biological gate**. Review
it before saving. New channels initially use linear coordinates. Set fluorescence
transforms in the recipe before adding fluorescence gates; the demo shows asinh.
Existing gates use the transforms already saved in their recipe.

## Sample sheets and outputs

The CSV must contain unique, nonempty `sample_id` and `fcs_path` columns.
Relative FCS paths resolve from the sample sheet's folder. Additional columns
(such as plate, well, condition, dose, replicate) are carried into the result
with a `metadata:` prefix. Samples run sequentially to bound memory usage.

Each run writes a new directory containing:

- `summary.csv`: root and gate counts, percent of parent, percent of total, and
  median signal for every configured channel. Medians use compensated signals
  before display transformations (raw signals when compensation is `none`).
- `gates-0001.png`, etc.: gate outlines on each parent population, indexed by
  sample-sheet row order. Plots use density binning; counts use all events.
- `recipe.json` and `samples.csv`: the recipe and sample sheet used.
- `run.json`: SHA-256 fingerprints of inputs, resolved compensation matrices,
  recipe/sample-sheet fingerprints, Python and package versions.

Runs never intentionally overwrite earlier output directories. Outputs are
published only after all samples succeed. Store raw files and results outside
Git; commit recipes, sample sheets when appropriate, and `uv.lock`. Input files
must remain available for a future rerun. Use a distinct output directory for
each concurrent run. Fingerprints identify inputs; they do not archive them.

## Recipe contract

JSON recipes have `version: 1`, `compensation`, `transforms`, and `gates` fields.
See the generated `demo/recipe.json` and `examples/make_demo.py` for a complete
example. Detector names must exactly match FCS **PnN** labels shown by `inspect`.
Gate names are globally unique; parents precede their children; `root` means all
events. Rectangle bounds are `[xmin, xmax, ymin, ymax]`, lower-inclusive and
upper-exclusive. Polygon vertices are pairs of coordinates.

**Every gate coordinate is in the channel's configured transformed space.**
Do not change transform parameters while keeping old vertices and assume the
same biological population will be selected. Both the editor and CLI use native
FlowKit gating with the same compensation and transform references.

Supported transforms:

```json
{
  "FSC-A": {"kind": "linear"},
  "FITC-A": {"kind": "asinh", "cofactor": 150},
  "PE-A": {"kind": "logicle", "parameters": {
    "param_t": 262144, "param_w": 0.5, "param_m": 4.5, "param_a": 0
  }}
}
```

Here `linear` means identity, and `asinh` means `arcsinh(signal / cofactor)`.
Parameters are fixed across samples, never estimated from each sample.

Compensation is always explicit:

- `{"mode": "none"}`: use uncompensated signals.
- `{"mode": "fcs"}`: require the matrix embedded in each FCS file; record each
  resolved matrix in the run. Missing metadata is an error.
- `{"mode": "matrix", "detectors": ["FITC-A", "PE-A"], "values": [[1, 0.12], [0.04, 1]]}`:
  apply the same labelled **spillover** matrix to all samples. Rows describe the
  source signal and columns the receiving detector: `measured = true @ matrix`.
  Supply coefficients as fractions, not percentages or an already inverted matrix.

This version applies compensation but **does not estimate matrices from controls**.
It does not automatically identify cells, singlets, or viable cells. It has no
plate normalization, hit calling, clustering, spectral unmixing interface, or
full FlowJo workspace editor. Those are separate future additions.

## Use from deliverome-analysis or another Python project

Install from a pinned commit for reproducible analyses:

```sh
uv add 'agentflow-cytometry @ git+https://github.com/Deliverome-Project/agentflow.git@<commit-sha>'
```

The repository is private, so GitHub access is required. Replace `<commit-sha>`
with a reviewed revision. Nothing needs to be copied into deliverome-analysis.

```python
from agentflow import analyze_sample, load_recipe

recipe = load_recipe("gates.json")
stats = analyze_sample("sample.fcs", recipe)  # pandas DataFrame
```

`from agentflow.batch import run_batch` exposes the same batch runner to Python.
Agents can inspect files, edit the JSON recipe, and run the CLI without a GUI.
GUI interaction is an optional human review step, not a prerequisite for reruns.

## Development

```sh
uv run ruff check .
uv run pytest -q
```

Tests use synthetic events with known spillover and populations. They cover
channel ordering, parent gating, compensated medians, repeatability, output
protection, missing compensation, and editor save/cancel/conflict callbacks.
These checks do not establish agreement with a particular laboratory's FlowJo
analysis. Compare representative real files and approved gates before adoption.

FlowKit is used as a dependency, not vendored or forked. See
[FlowKit](https://github.com/whitews/FlowKit) for its source and documentation.
