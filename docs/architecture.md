# Architecture

```
CLI / Python API              Matplotlib GateEditor
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
| `editor.py` | Temporary editable recipe, gate navigation, selectors, undo/redo, save/cancel |
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
