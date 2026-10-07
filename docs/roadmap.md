# Cytometry features to prioritize

The [workspace design](design/workspace-workflows.md) describes proposed
GUI/CLI/Python/YAML contracts and staged acceptance criteria. Proposed interfaces
are not necessarily implemented yet.

| Capability | Current release | Next step / value for screens |
|---|---|---|
| Hierarchical gates | Polygon, rectangle, range, linked orthogonal quadrants and AND/OR; native shared engine | Validated ellipse tools if needed |
| Gate review | Unfinished populations, named Undo, breadcrumbs, display detector exploration, searchable review queue, checkpoints/recovery, linked control comparison and parent highlighting | Validation against representative lab workflows |
| Compensation | Embedded/imported matrices, interactive single-stain threshold review/calculation, before/after plots | Interactive cleanup gates, separate negative files; alternative estimators validated against lab controls |
| Fluorescence display | Fixed recipes, original-unit ticks/thresholds, axis display previews | Editable transform parameters and reviewed polygon migration |
| Templates | Shared recipe with explicit sample exceptions, missing-channel failures | Instrument/panel presets |
| Quality control | Searchable per-sample flags for low counts, empty parents, upper range, backward time and compensation status | Time exclusion gates and assay-specific QC thresholds |
| Screen reporting | Metadata, plate maps, control normalization, well summaries and explicit hit cutoff | Assay-specific exclusions, dose-response fitting and statistical hit review |
| Interchange | GatingML export; broader vendored API | Validated imports and reference comparison fixtures, preserving provenance |
| Agent workflows | CLI JSON status, importable API, immutable run directories | Stable JSON Schema, recipe diff summaries and review automation |
| Sharing/install | Private Git install, locked environment, tests and wheel build | Versioned releases after representative team validation |

Recommended next work is representative scientist usability/validation sessions,
followed by explicit analysis sets and reusable endpoint/report definitions.
Recipes already support JSON/YAML; a full portable workspace remains separate future work.
Control-cleanup editing and real-control validation remain required for scientific confidence.
Do not add clustering, dimensionality reduction or a full workspace clone before
we have validated the basic few-channel workflow on real experiments. Screen
normalization and hit calling require an agreed experimental design, not a generic
software default.
