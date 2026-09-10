# FlowJo-style features to prioritize

| Capability | Current release | Next step / value for screens |
|---|---|---|
| Hierarchical gates | Polygon, rectangle, 1D range; shared GUI/CLI execution | Quadrants and Boolean combinations for co-expression |
| Gate review | Gate navigation, undo/redo, parent-aware counts, review flags | Multiple samples in one editor; control/sample overlays |
| Compensation | Embedded/imported matrices, explicit control estimator, before/after plots | Interactive control-population review; alternative estimators validated against lab controls |
| Fluorescence display | Fixed linear/asinh/logicle recipes; histogram editor | Tick labels in original units; transform editing with gate migration review |
| Templates | Same recipe across samples, missing-channel failures | Instrument/panel presets and explicit per-sample overrides |
| Quality control | Time plots, upper-range flags, empty-parent handling | Time exclusion gates, low-count thresholds and batch-level QC summaries |
| Screen reporting | Metadata-preserving tidy tables and per-sample reports | Plate heatmaps, replicate summaries, controls-based normalization and hit calling |
| Interchange | GatingML export; broader vendored API | Validated imports and FlowJo comparison fixtures, preserving provenance |
| Agent workflows | CLI JSON status, importable API, immutable run directories | Stable JSON Schema, recipe diff summaries and review automation |
| Sharing/install | Private Git install, locked environment, tests and wheel build | Versioned releases after representative team validation |

Highest-value next additions are sample/control overlays and plate summaries.
Do not add clustering, dimensionality reduction or a full workspace clone before
we have validated the basic few-channel workflow on real experiments. Screen
normalization and hit calling require an agreed experimental design, not a generic
software default.
