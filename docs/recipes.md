# Recipe reference (versions 1 and 2)

Required fields: `version: 1` or `version: 2`, `compensation`, `transforms`, `gates`.
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


AND/OR co-expression gates reference earlier populations. `channels` specifies the
2D view; the native Boolean operation determines membership, within `parent`.
Changing a referenced gate invalidates review of the combination.

```json
{"name":"double_positive", "parent":"live", "kind":"boolean",
 "operation":"and", "references":["gfp","mscarlet"],
 "channels":["BL1-A","YL2-A"], "reviewed":false}
```


## Version 2 workspace additions

Creating an unfinished population or linked quadrants upgrades the recipe to
`version: 2`. Existing version-1 recipes remain supported without migration.
Older Agentflow builds reject version 2 rather than silently omitting unfinished
populations. Completing/deleting unfinished populations does not downgrade the
recipe; use the upgraded build for replay. Undo/checkpoints can restore the prior
version as part of restoring the prior complete recipe.

`draft_gates` stores named unfinished populations separately from executable
`gates`. Each entry has `name`, an existing executable `parent`, `kind` (rectangle,
polygon or range), and `channels` (two distinct transformed detectors; a range
may use one). It contains no geometry and has no membership/count. Draft names
cannot collide with completed or unmapped populations. Execution and GatingML
export reject nonempty `draft_gates`; only explicit editor previews evaluate the
completed portion. Saving/recovery retain the unfinished definitions.

`kind: quadrant` has two channels, four bounds and a `quadrant_group` string.
Exactly four members share parent, channels and thresholds. Each detector has
one finite endpoint and one unbounded endpoint; the four combinations partition
the parent with threshold events assigned to the positive side. Native FlowKit
RectangleGates execute these definitions. Changing only one quadrant threshold
is invalid; linked edits update all four, including per-sample exceptions.
