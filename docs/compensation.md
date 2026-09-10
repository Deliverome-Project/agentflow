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
matching autofluorescence backgrounds/particle types. Saturated source positives,
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
show the full control (at most roughly 5000 points via deterministic stride),
so the effects of cleanup can be inspected separately. Check threshold placement
and off-diagonal residual distributions; a coefficient heatmap alone is not QC.
The estimate records control hashes, selection thresholds, median signals,
population counts, config and cleanup fingerprints; it remains `reviewed: false`.

FlowJo's own guidance also emphasizes control assignment, cleanup and
positive/negative gate review, and adequate control brightness:
[compensation workflow](https://docs.flowjo.com/flowjo/experiment-based-platforms/plat-comp-overview/plat-comp-workflow/),
[compensation FAQ](https://www.flowjo.com/docs/flowjo10/experiment-based-platforms/plat-comp-overview/plat-comp-faq).

CSV/TSV import accepts a labelled square table with source detector names in the
first column and target names in the first row. It is not an unrestricted parser
for every vendor's matrix export dialect. Convert headers/units deliberately.
