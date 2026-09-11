# Compensation controls

The experimental sample alone does not determine a compensation matrix. Use the
instrument's embedded matrix, a reviewed labelled matrix, or single-stain
controls acquired with matching settings. An identity matrix provides no
spillover correction.

The independent estimator uses two populations **within each single-stain file**:

```
spill[source, target] = (median(target_positive) - median(target_negative))
                     / (median(source_positive) - median(source_negative))
```

Both sets are selected using explicit raw source-detector thresholds. This needs
matching autofluorescence backgrounds/particle types. Saturated positive or negative
events in any included detector (source or receiving),
too-small populations, invalid labels and ill-conditioned matrices fail. Controls
need sufficient brightness; these checks cannot establish experimental suitability.
This is not Cytoflow's through-origin regression or FlowJo's AutoSpill algorithm.
No Cytoflow source or GPL dependency has been copied into agentflow.

```json
{
  "detectors": ["BL1-A", "YL2-A"],
  "min_events": 50,
  "controls": [
    {"detector":"BL1-A", "fcs_path":"gfp-only.fcs", "negative_max":500, "positive_min":10000},
    {"detector":"YL2-A", "fcs_path":"mscarlet-only.fcs", "negative_max":500, "positive_min":10000}
  ]
}
```

Threshold values above are placeholders, not recommended universal settings.
Paths resolve relative to this config. For debris/singlet cleanup, add
`cleanup_recipe` and `cleanup_gate`; that recipe must use compensation `none`.
The estimator uses all events passing cleanup. The before/after diagnostic plots
show that same population (at most 5000 points via deterministic stride), using
the cleanup recipe embedded in the estimate and the native FlowKit matrix path.
Check threshold placement
and off-diagonal residual distributions; a coefficient heatmap alone is not QC.
The estimate records control hashes, selection thresholds, median signals,
population counts, config and cleanup fingerprints; it remains `reviewed: false`.

Here, raw means uncompensated signal after FlowKit/FlowIO's acquisition gain and
amplification preprocessing. Saturation limits are converted to those same units;
they are not compared directly with unscaled FCS range values. No display transform
or clipping of negative compensated values is part of compensation.

New estimates record detector gain, range, amplification and reported voltages,
plus the reported instrument. Contradictory settings across controls or between
controls and an analysis sample fail. Missing reference metadata remains unknown;
matching reported fields does not establish that unreported settings, particles,
or instrument performance are suitable. Older and imported matrices without this
metadata retain label/matrix validation but cannot get this acquisition comparison.

FlowJo's own guidance also emphasizes control assignment, cleanup and
positive/negative gate review, and adequate control brightness:
[compensation workflow](https://docs.flowjo.com/flowjo/experiment-based-platforms/plat-comp-overview/plat-comp-workflow/),
[compensation FAQ](https://www.flowjo.com/docs/flowjo10/experiment-based-platforms/plat-comp-overview/plat-comp-faq).

CSV/TSV import accepts a labelled square table with source detector names in the
first column and target names in the first row. It is not an unrestricted parser
for every vendor's matrix export dialect. Convert headers/units deliberately.

The native workbench now exposes this same estimator through **Calculate
compensation…**, with file assignment, raw-unit threshold fields, clickable control
histograms and minimum-event settings. Load this JSON format to include an
uncompensated cleanup recipe. Export creates a new review directory atomically;
applying the resulting matrix is a separate action and clears gate review flags.
Edits to control inputs invalidate the previous calculation. Python callers can use
`agentflow.control_review.export_control_review(config, output)` with absolute input
paths; `resolve_config(config, base_directory)` converts a file-relative config first.
Separate unstained negative files, regression/AutoSpill and suitability assessment
against representative lab controls remain outstanding.

See [compensation audit](compensation-audit.md) for code comparisons, regression
coverage and remaining limitations.
