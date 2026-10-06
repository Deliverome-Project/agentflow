# Channel names and density plots

Detector IDs (`$PnN`) remain the keys for compensation, transforms, gate geometry
and exports. Plot axes, detector selectors and the detector-information dialog
show readable names alongside those IDs. Names are resolved separately for each
sample, in this order:

1. A nonempty, distinct `$PnS` from that sample's FCS header.
2. For an instrument whose recorded `$CYT` contains `CytoFLEX`, the laboratory
   channel aliases supplied with this change, when the detector is `FLn-A` or
   `FLn-H`.
3. The original detector ID, with stain identity explicitly unknown in the
   detector-information dialog.

The CytoFLEX fallback is a supplied laboratory configuration, not a universal
CytoFLEX panel or proof of a stain. File metadata takes precedence. The dialog
shows the source of every name; unknown instruments do not inherit this mapping.
No compensation, biological role, or gate is inferred from an alias.

| CytoFLEX detector | Supplied channel alias (A and H) |
| --- | --- |
| FL1 | PB450 |
| FL2 | KO525 |
| FL3 | Violet610 |
| FL4 | Violet660 |
| FL5 | FITC |
| FL6 | PerCP |
| FL7 | PE |
| FL8 | ECD |
| FL9 | PC5.5 |
| FL10 | PC7 |
| FL11 | APC |
| FL12 | APC-A700 |
| FL13 | APC-A750 |

## MA900 evidence

A read-only inspection of 18 locally cached S3E9 Sony training FCS exports
(including FCS 3.1 copies) found `$CYT=LE-MA900FP` and these explicit pairs:

| `$PnN` | `$PnS` |
| --- | --- |
| FL1-A | Alexa Fluor 488-A |
| FL6-A | Brilliant Violet 421-A |
| FL10-A | Alexa Fluor 647-A |

Nineteen earlier cached reporter-experiment files from the same instrument type
recorded `FL3-A` → `mScarlet3-A`. Historical S3E9 analysis code independently used
FL1-A for the ALFA probe and FL10-A for the Spy probe. Those biological roles
belong to that experiment; they are not instrument-wide defaults. These four
names are therefore read automatically from `$PnS`, not hardcoded onto every
MA900 file. Missing metadata remains unknown. Tests use synthetic fixtures
representing these fields; no experimental event data is included or scientifically
validated by these tests. There is no dependency on the historical analysis code.

## How FlowJo handles this

[FlowJo's parameter documentation](https://flowjo.com/docs/flowjo11/metadata-manager-2-2/parameters-2-2)
describes fluorochrome names from `$PnN` and stain names from `$PnS`, with editable
workspace names. [Its instrument preferences](https://www.flowjo.com/docs/flowjo10/workspaces-and-samples/flowjo-and-your-cytometer/ws-instrumentation)
use `$CYT` and `$SYS` to choose instrument-specific scaling, falling back to
generic settings when the instrument is unknown. Agentflow displays the recorded
`$CYT`; acquisition provenance retains `$SYS`. It does not silently change
analytical transforms based on instrument recognition.

An instrument name, laser wavelength or filter band alone does not uniquely
identify the stain used. Explicit acquisition labels are the reliable automatic
source here; historical experimental labels are supporting evidence, not a way
to reconstruct an unrecorded panel.

## Dot plots and exact counts

The default is **Density dots**, colored blue → cyan → green → yellow → red from
low to high density on a logarithmic color scale. Density is calculated from
all finite parent events in 128 × 128 bins in recipe coordinates (within the
display range when clipped); at most 20,000 deterministic display points are
drawn, with dense points last. This is a binned approximation for visualization,
not a reproduction of FlowJo's density estimator. Alternate nonlinear display
axes do not change the underlying density bins. Group overlays use group-colored
contours so the density color scale does not erase sample identity.

Threshold gates previously always drew histograms because their analytical gate
has only one channel. They now default to that channel versus SSC-A (or another
available transformed channel). **Plot settings → Threshold plot Y** changes the
second display channel. **Histogram** restores the one-dimensional view. A
single-channel recipe still falls back to a histogram. Two-dimensional gates
always retain both axes. Display choices are saved in the recipe and used by
headless QC plotting too.

The additional axis, colors and point cap never change the gate dimensions,
membership masks, compensation, exact counts or statistics. FlowKit still
evaluates every event using the same shared recipe.
