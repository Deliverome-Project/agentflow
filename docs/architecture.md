# Architecture

```
CLI / Python API              Qt + Matplotlib ScreenWindow
        |                      | recipe edits only
        +---------- recipes ---+
                       |
                   engine.py
                       |
           vendored FlowKit GatingStrategy
                       |
               counts / event masks
                       |
         batch -> plots + QC + HTML report
```

| Module | Responsibility |
|---|---|
| `recipes.py` | Versioned recipe validation, atomic persistence, fingerprints |
| `compensation.py` | Labelled matrix validation/import/application; independent control estimator |
| `workflow.py` | Draft gates, explicit role mappings, unavailable steps, review invalidation |
| `engine.py` | Sample preparation, native FlowKit compilation/execution, statistics |
| `editor_state.py` | Toolkit-independent transactions, validation, history, review invalidation and atomic saving |
| `desktop.py` | Base single-sample native controls and Matplotlib selectors |
| `workbench.py` | Multi-sample navigation, population/sample galleries, plate map and overlays |
| `samples.py` | Sample-sheet validation, group colors, per-sample matrices and bounded preview cache |
| `plot_views.py` | Shared scatter/density/histogram rendering, original-unit ticks and reversible display axes |
| `screening.py` | Explicit control normalization, plate summaries and well-level descriptive aggregates |
| `cache.py` | Verified, content-addressed reuse of identical batch outputs |
| `theme.py`, `assets/fonts/` | Deliverome tokens and bundled Manrope/Playfair Display fonts and licenses |
| `editor.py` | Legacy Matplotlib-only editor retained for compatibility; not used by the CLI |
| `batch.py` | Sample manifests, sequential execution, staging, reproducible run records |
| `plots.py`, `quality.py`, `reporting.py` | Headless figures, acquisition flags, escaped HTML report |
| `demo.py` | Seeded synthetic full workflow and controls |
| `vendor_info.py` | Upstream identity and actual vendored code/resource fingerprint |

The editor and CLI use the same recipe and evaluator. Gate edits never operate
on a plotted subsample. Transformation parameters are fixed across samples.
Compensation resolves detector names before numerical work; gate dimensions
reference the correct matrix and transform. The data flow is compensation →
transformation → gating. Reported medians are before transformation.

No GUI backend is selected by the analysis engine or batch plotting. Qt is an
optional extra loaded only for desktop editing. The vendored FlowKit code still
uses its declared scientific dependencies and its upstream Bokeh plotting API.
We maintain its copy separately from application code and preserve source notices.

Extension rules: add tests with known populations/matrices for scientific changes;
never silently guess marker identity, skip samples, or treat draft thresholds as
validated biology. Add new gate types to validation, native compilation, editor,
plots and roundtrip tests together. Keep experimental data out of tests and Git.

Matplotlib is constrained below 3.11 because its 3.11 TextBox resize callback
assumes mouse-event fields on a ResizeEvent. The native desktop smoke check
exposed this; a synthetic resize-event test now guards it. Re-evaluate the bound
when upstream fixes that callback and the GUI suite passes against the new release.

`overrides.py` validates restricted per-sample geometry/review patches and resolves
effective recipes; `samples.py` applies these before both preview and batch evaluation.
`control_review.py` publishes atomic compensation review bundles using the headless
estimator. `compensation_wizard.py` supplies optional Qt control assignment/threshold
review and never implements a separate compensation formula.
