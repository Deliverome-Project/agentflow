# FlowJo-style features to prioritize

| Capability | Current release | Next step / value for screens |
|---|---|---|
| Hierarchical gates | Polygon, rectangle, range and AND/OR co-expression; shared engine | Quadrant creation presets |
| Gate review | Multi-sample navigation, population/sample galleries, overlays, undo/redo, review flags | Pinned controls and explicit per-sample gate exceptions |
| Compensation | Embedded/imported matrices, explicit control estimator, before/after plots | Interactive control-population review; alternative estimators validated against lab controls |
| Fluorescence display | Fixed recipes, original-unit ticks/thresholds, axis display previews | Editable transform parameters and reviewed polygon migration |
| Templates | Same recipe across samples, missing-channel failures | Instrument/panel presets and explicit per-sample overrides |
| Quality control | Time plots, upper-range flags, empty-parent handling | Time exclusion gates, low-count thresholds and batch-level QC summaries |
| Screen reporting | Metadata, plate maps, control normalization, well summaries and explicit hit cutoff | Assay-specific exclusions, dose-response fitting and statistical hit review |
| Interchange | GatingML export; broader vendored API | Validated imports and FlowJo comparison fixtures, preserving provenance |
| Agent workflows | CLI JSON status, importable API, immutable run directories | Stable JSON Schema, recipe diff summaries and review automation |
| Sharing/install | Private Git install, locked environment, tests and wheel build | Versioned releases after representative team validation |

Next additions are pinned controls, explicit per-sample gate exceptions and validation on representative lab controls.
Do not add clustering, dimensionality reduction or a full workspace clone before
we have validated the basic few-channel workflow on real experiments. Screen
normalization and hit calling require an agreed experimental design, not a generic
software default.
