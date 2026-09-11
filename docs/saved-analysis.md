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
and display its scatter plot. The plot opens focused; uncheck **Focus plot** to
restore the population gallery. The detector pair is editable; dye roles are only
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
