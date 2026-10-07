# Gate editing and workspace review — October 2026

This review addresses Brenna's gate-type feedback and Maria's polygon-point
feedback. It compares documented FlowJo v10 workflows, not measured product
parity or real-sample validation.

## Shipped in this change

| Workflow | FlowJo documentation | Agentflow decision |
|---|---|---|
| Choose a shape near the data | Graph-window gating tools | Create a named unfinished population with Choose in plot; show Gate type immediately above the canvas |
| Change an existing shape | Selected-gate context menu supports conversion | Visible rectangle/polygon/range selector; retain hierarchy and sample exceptions; Undo restores the transaction |
| Refine a polygon | Drag individual vertices and move whole gates | Retain dragging and Ctrl+click; expose Add point as a one-click insertion mode and Redraw beside it |
| See impact on descendants | Gate edits recalculate child statistics | Continue using native FlowKit masks and all events; invalidate dependent review status |
| Work on smaller displays | Graph window separates plot and gate controls | Keep drawing controls in a short row inside the plot card; retain Focus plot, resizable gallery and scrollable supporting controls |

Sources: [Graph Window](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-overview/),
[Drawing Gates](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-gating/gw-gatedrawing/),
[Editing Gates](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-gating/gw-gatechanging/).
The cited editing page does not establish arbitrary polygon vertex insertion;
Agentflow's Add point is a response to user feedback, not a claim of FlowJo parity.

## Scientific and interaction boundaries

Choose in plot now stores an unfinished population with no geometry or count.
It can be saved and recovered, but blocks execution and gate export until drawn
or deleted. Existing completed gates retain their prior boundary while a
replacement is being drawn; Escape restores it. Completed but unreviewed gates
remain distinct from unfinished populations.

Conversion operates in recipe coordinates. Polygon-to-rectangle uses its bounding
box and range conversion projects onto X; neither promises preserved membership.
Rectangle-to-polygon edge inclusion can differ under native FlowKit semantics.
Range-to-2D requires a detector choice and initializes finite limits from the
current sample. All converted shared and sample-exception geometry is validated
atomically. No compensation, channel mapping or gate execution math is added to
the GUI. The polygon edge-distance calculation chooses an editing handle only.

## Remaining priorities

1. Usability review with Brenna and Maria on representative controls, especially
   draft visibility, conversion expectations and trackpad vertex editing.
2. Clear template/group ownership before adding overlapping analysis groups or
   bulk exception promotion; background loading for individual large FCS files.
3. A reusable report-layout and endpoint builder for consistent sample comparisons.
4. Interactive compensation cleanup and representative scientific validation.

Linked orthogonal quadrants (native FlowKit rectangles), a searchable sample
review queue, control comparison, parent highlighting, checkpoints/recovery and
navigation improvements now address the first workspace usability priorities.
Ellipses, freehand/autogating, report boards and FlowJo workspace import remain
follow-up work. Existing tree,
parent navigation, ancestry gallery, display previews, scope controls and all-event
statistics already cover the immediate review workflow. The broader roadmap is
in [workspace workflows](workspace-workflows.md). Automated verification uses
synthetic fixtures only.
