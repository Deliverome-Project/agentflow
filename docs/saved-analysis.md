# Recipes, review and reproducibility

Edit **one recipe**, in YAML or JSON. Both formats describe the same Python data
structure and `agentflow edit`, `run` and `validate` accept either. The scaffold
still uses `recipe.json` for compatibility; users do not need to maintain both.
For example, `agentflow run samples.csv --recipe recipe.yaml --out run-002`.

The generated `*.reproducibility.yaml` (editor) or `reproducibility.yaml` (batch)
is a snapshot containing the recipe, Agentflow source/commit identity and Python
environment. It can be loaded as a recipe for a rerun. Editing a snapshot does not
recreate its recorded environment automatically. Treat snapshots as run records;
edit the recipe for the next run. Batch `run.json` is a machine-readable execution
manifest, also embedded in the YAML; it is not another user-maintained config.
It remains for existing report/cache consumers. A rerun creates a new directory.

Editor snapshots record instrument metadata for the inspected sample. Batch
snapshots record it for every input under `run.inputs[].instrument`, including
instrument model/name, serial number, acquisition date/time, reported acquisition
software, detector gain, voltage, range and amplification, plus original FCS
keyword values with normalized lowercase keys. Missing fields are null, never
inferred. FCS metadata is instrument-reported, not independently verified. Raw
keywords may include operator/sample identifiers; inspect them before sharing.

## Draft versus reviewed

`reviewed: false` means no current human sign-off, not a failed analysis. New gates
start as drafts. Geometry/parent changes invalidate affected populations, and a
compensation change invalidates all gate review because the signal space changed.
Use **Mark reviewed →** after checking a gate. Saving preserves geometry and
review state; it does not silently approve the analysis. Sample-specific review
may be recorded in `sample_overrides` while the shared gate remains unreviewed.

## Histogram and reporter ratio gates

New histogram populations default to **Between bounds**. Existing one-sided
recipes retain their selection until the user changes it. Reporter initialization
uses finite data-derived bounds as a draft, not biological thresholds.

**GFP / Cy5…** opens a labelled-detector dialog to create a shared ratio population
and display its scatter plot. The population gallery remains visible. **Focus plot** can hide it when
you want more space for the active plot. The detector pair is editable; dye roles are only
initial selections. Ratio = numerator signal / denominator signal after the chosen
compensation and before asinh/logicle display transforms. The lower ratio bound is
inclusive and upper bound exclusive. Denominator must be strictly greater than the
explicit nonnegative cutoff; nonpositive/near-zero backgrounds should be excluded
using a cutoff justified by controls. Signal ratios are instrument-dependent, not
molecular abundance ratios. Reopen this action on a ratio population to edit it.
The plot shows both ratio boundaries and the denominator cutoff. Child gates and
batch summaries use the same FlowKit hierarchy. Ratio gates export as standard Gating-ML ratio transformations, ratio dimensions
and a denominator bound. The compensated definition and parent hierarchy survive
export/import; other software must correctly implement the compensation reference
on ratio dimensions. Agentflow corrects that behavior in its vendored FlowKit.

## Relationship to cytometry standards

[ISAC's standards](https://isac-net.org/data-standards/) cover complementary parts:

- **FCS** stores event data and acquisition keywords.
- **MIFlowCyt** specifies minimum reporting information for the experiment,
  samples, instrumentation and analysis; it is not a YAML schema.
- **Gating-ML** exchanges mathematical gate, transformation and compensation
  definitions. Agentflow supports export for its supported standard gate types.
- **CLR** exchanges event classification results; **ACS** describes bundling
  cytometry data and analysis artifacts.

Agentflow YAML is an application-specific reproducibility record, not a claim of
MIFlowCyt compliance or an implementation of ACS/CLR. Instrument metadata alone
cannot supply missing biological context, reagent identities or control design.

Event counts and review actions stay outside the scrolling plot settings. The
comparison gallery fits a page of plots to its available height and width; use
the left/right arrows for more plots. Resizing the window or divider updates
the page capacity. The default gating view fits at 980×620 and larger.

### Explore detectors and create subpopulations

Select a population in the tree, then use **New subpopulation…** to create a
child, sibling, or a population under another parent. Choose the gate shape and
acquired detector names; reshape the draft on the main plot. Histogram gates
start **Between bounds**. Above/below remain explicit options. Existing saved
one-sided gates retain their intended meaning; the synthetic demo now uses two
finite bounds too.

**Scatterplot…** opens an inspection window: choose a population, X/Y detectors,
and scatter, density, or contour. This temporary view does not change the recipe.
**Create subpopulation on these axes…** carries that population and detector pair
into the gate dialog. The resulting gate is saved with the recipe through the
normal Save action. Detector axis transformations come from the recipe.

### Standards and gate interchange

MIFlowCyt (Minimum Information about a Flow Cytometry Experiment) describes
reporting requirements for the experiment, samples, instrument, and analysis;
it is not a gating library or file format. Agentflow captures acquisition
metadata and analysis provenance, but does not certify MIFlowCyt completeness.
See [ISAC data standards](https://isac-net.org/data-standards/).

Each batch run now exports `gates-0001.gatingml.xml`, etc. using FlowKit's native
Gating-ML 2.0 exporter. The corresponding sample ID is recorded in run provenance,
and the report links each file. Each export includes that sample's effective gate
hierarchy, transforms and resolved compensation, including sample exceptions and
ratio gates. Use these XML files for gate interchange; keep the YAML recipe and
sample sheet for Agentflow's review flags, groups, display settings and reruns.
The CLI also supports `agentflow export-gml sample.fcs --recipe recipe.yaml
--out gates.xml` (use `--sample-id` when the recipe contains sample exceptions).
Gating-ML round-trip tests check event membership, including compensation; other
applications' import support still varies.

The desktop uses white surfaces with a pale neutral sidebar. Comparison thumbnails
use a compact grid (two columns when panel width permits) and show at least two
plots per page at supported window sizes. Selecting a thumbnail still opens its
sample or population in the main editable plot.

### Remove a subpopulation

Right-click the population and choose **Delete population…**, or use
**Analysis → Delete selected population…**. The confirmation lists the selected
population, its descendants, and Boolean populations that depend on them. They
are removed together, including their sample exceptions; unrelated gates retain
their definitions. Use **Undo** to restore the change or **Save** to persist it.
Population structure is shared, so select **All samples** first. The editor
currently requires at least one population to remain.

The synthetic demo's low/high groups mean low/high **positive fraction**, not
low/high fluorescence per positive cell. Each reporter independently receives
positive signals with probabilities 5%, 25%, and 60% across the three samples.
The same positive signal increment is used in all three. These are predefined
sample-sheet groups, not inferred classifications, and the demo negative control
is not an unstained control.

### Build a sample sheet after acquisition, including agent / Notion notes

```sh
agentflow sample-sheet path/to/fcs-folder --out draft-sheet
agentflow sample-sheet path/to/fcs-folder --annotations notes.yaml --out annotated-sheet
```

Both commands create `samples.csv`, `acquisition.json`, and a copy of the annotation
input. Files are scanned recursively, with stable relative-path sample IDs.
Unspecified group, condition, plate, well and replicate fields remain blank.
The sheet records input SHA-256 values; batch execution rejects changed inputs.
Review the draft identities and assignments before analysis. Control files are
included if present in the folder; explicitly assign their role or remove them
from the analysis sheet as appropriate.

An agent can read a scientist-selected Notion experiment page through its Notion
connector, then create this annotation input. Agentflow itself does not fetch
Notion pages or store Notion credentials. This separation lets the same importer
accept scientist-authored notes and other ELNs. Annotations match **exact relative
FCS filenames**, never fuzzy matches. Duplicate or unmatched annotations fail.
Agents should leave `reviewed: false` until the scientist confirms assignments.
Ask about missing or contradictory identities instead of guessing. For example:

```yaml
samples:
  - file: plate-1/well-A01.fcs
    source_url: https://www.notion.so/your-experiment-page
    reviewed: false
    metadata:
      sample_id: treated-replicate-1
      group: treated
      plate: plate-1
      well: A01
      biological_replicate: 1
      instrument_user_reported: Attune
```

Custom scalar metadata columns are preserved. FCS acquisition fields have a
`fcs:` prefix and cannot be overridden by annotations. User-reported instrument
information stays separate from FCS-reported values. Notion links identify the
annotation source; the copied annotation file preserves what was actually used.
There is no automatic synchronization with later Notion edits.

### Event-level data and summary statistics

Every batch run now writes one `events.parquet`, separate from `summary.csv`:

- One row per acquired event, including events outside every gate; no plot downsampling.
- `sample_id` + zero-based `event_index` identify the original event, with `input_sha256`.
- `raw:<detector>` contains FlowKit-preprocessed uncompensated values (which may
  account for acquisition gain/log encoding/time scaling), **not original encoded
  FCS numbers**. Retain the original FCS for the primary acquisition record.
- `signal:<detector>` contains compensated values when compensation is assigned,
  otherwise uncompensated values, always before display transformations.
- `gate:<population>` is a Boolean membership column, including `gate:root`.
- `metadata:<field>` repeats sample-sheet metadata on each event. `instrument_json`
  contains acquisition settings and all FCS keywords; `compensation_json` records
  the resolved matrix. Parquet schema metadata includes the recipe and Agentflow identity.
- Detector columns span the union of acquired detectors; absent detectors are null.

The writer streams batches into a compressed Parquet file rather than collecting
all samples' events in memory. Input preparation still loads one FCS sample.

For every gate and recipe detector, summary CSV now includes arithmetic mean,
median, sample standard deviation (`ddof=1`), minimum, maximum, 5th/25th/75th/95th
percentiles, and finite-value count. Statistics use pre-display signal values;
nonfinite values are excluded and the finite count exposes that exclusion.
Empty populations have missing statistics; standard deviation is missing for
fewer than two finite events. Gate event counts are unaffected. Geometric means
and CV are deliberately not emitted because compensated signals can be zero or
negative. These are descriptive cell-level statistics, not replicate-level errors.
