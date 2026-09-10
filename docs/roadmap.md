# FlowJo-style features to prioritize

| Capability | Current release | Next step / value for screens |
|---|---|---|
| Hierarchical gates | Polygon, rectangle, range and AND/OR co-expression; shared engine | Quadrant creation presets |
| Gate review | Multi-sample galleries, pinned overlays, explicit sample exceptions, undo/redo, review flags | Validation against representative lab workflows |
| Compensation | Embedded/imported matrices, interactive single-stain threshold review/calculation, before/after plots | Interactive cleanup gates, separate negative files; alternative estimators validated against lab controls |
| Fluorescence display | Fixed recipes, original-unit ticks/thresholds, axis display previews | Editable transform parameters and reviewed polygon migration |
| Templates | Shared recipe with explicit sample exceptions, missing-channel failures | Instrument/panel presets |
| Quality control | Time plots, upper-range flags, empty-parent handling | Time exclusion gates, low-count thresholds and batch-level QC summaries |
| Screen reporting | Metadata, plate maps, control normalization, well summaries and explicit hit cutoff | Assay-specific exclusions, dose-response fitting and statistical hit review |
| Interchange | GatingML export; broader vendored API | Validated imports and FlowJo comparison fixtures, preserving provenance |
| Agent workflows | CLI JSON status, importable API, immutable run directories | Stable JSON Schema, recipe diff summaries and review automation |
| Sharing/install | Private Git install, locked environment, tests and wheel build | Versioned releases after representative team validation |

Next additions are control-cleanup editing, editable transform parameters and validation on representative lab controls.
Do not add clustering, dimensionality reduction or a full workspace clone before
we have validated the basic few-channel workflow on real experiments. Screen
normalization and hit calling require an agreed experimental design, not a generic
software default.
