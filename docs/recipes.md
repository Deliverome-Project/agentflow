# Recipe reference (version 1)

Required fields: `version: 1`, `compensation`, `transforms`, `gates`.
Gate names are globally unique; `root` represents all events; parents must appear
before children. Optional fields include `experiment`, `pending_gates`,
`channel_roles`, and per-gate `label`, `note`, `reviewed`.

Transforms per PnN channel:

```json
{
  "FSC-A": {"kind": "linear"},
  "BL1-A": {"kind": "asinh", "cofactor": 150},
  "YL2-A": {"kind": "logicle", "parameters": {
    "param_t": 1048576, "param_w": 0.5, "param_m": 4.5, "param_a": 0
  }}
}
```

`linear` is identity; `asinh` is arcsinh(signal/cofactor). Every gate coordinate
uses the configured transformed space. Changing transforms requires reviewing
all affected gate coordinates; do not assume old polygons identify the same
population after a scale change.

| Kind | Channels | Shape |
|---|---|---|
| polygon | two | `vertices: [[x,y], ...]`, at least three noncollinear vertices |
| rectangle | two | `bounds: [xmin,xmax,ymin,ymax]` |
| range | one | `bounds: [min,max]`; either endpoint may be `null` for unbounded |

Range and rectangle lower bounds are inclusive, upper bounds exclusive. Polygon
membership uses FlowKit's native winding algorithm. Empty parents produce zero
child events and an undefined percentage of parent.

Compensation `mode` is `none`, `fcs`, or `matrix`. Matrix mode requires unique
`detectors` and square finite `values`; diagonal 1, fractions, source rows and
receiving-detector columns. FCS mode fails if no embedded spillover exists.

`init` builds draft scatter envelopes (nonnegative scatter, 2nd–98th percentile)
and an area/height singlet band around the median ratio in the central scatter
population. These are starting drawings, not automatic cell identification.
Fluorescence drafts use a threshold at the 80th percentile of their parent on
the selected template sample; live selects below it, reporter gates above it.
The resulting initial 20% reporter fractions are **by construction**, not a
biological discovery. Set boundaries using appropriate controls before analysis.
Once created, numeric bounds are saved and reused unchanged across samples.

Review flags are annotations, not an access-control mechanism. Batch execution
allows draft gates and makes their status explicit in reports and tables. A human
must decide when results are suitable for experimental conclusions. `is_example`
remains true after review; changing a gate does not promote a dummy experiment.
