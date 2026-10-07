# Gate editing and workspace review — October 2026

This review addresses Brenna's gate-type feedback and Maria's polygon-point
feedback. It compares documented FlowJo v10 workflows, not measured product
parity or real-sample validation.

## Shipped in this change

| Workflow | FlowJo documentation | Agentflow decision |
|---|---|---|
| Choose a shape near the data | Graph-window gating tools | Create a named draft with Choose in plot; show Gate type immediately above the canvas |
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

Choose in plot uses a provisional rectangle, not an ungated population. The dialog
states its 10th–90th percentile initialization; displayed counts refer to that
boundary until it is replaced. Saved draft gates remain executable like existing
Agentflow drafts; users must review them before interpreting results.

Conversion operates in recipe coordinates. Polygon-to-rectangle uses its bounding
box and range conversion projects onto X; neither promises preserved membership.
Rectangle-to-polygon edge inclusion can differ under native FlowKit semantics.
Range-to-2D requires a detector choice and initializes finite limits from the
current sample. All converted shared and sample-exception geometry is validated
atomically. No compensation, channel mapping or gate execution math is added to
the GUI. The polygon edge-distance calculation chooses an editing handle only.

## Remaining priorities

1. Orthogonal quadrants for two-reporter screens, with boundary conservation tests.
2. A searchable sample table and clear template/group ownership before adding
   overlapping analysis groups or bulk exception promotion.
3. A reusable report-layout and endpoint builder for consistent sample comparisons.
4. Usability review with Brenna and Maria on representative controls, especially
   draft visibility, conversion expectations and trackpad vertex editing.

These remain follow-up work; this change does not add ellipses, quadrants,
freehand/autogating, report boards or FlowJo workspace import. Existing tree,
parent navigation, ancestry gallery, display previews, scope controls and all-event
statistics already cover the immediate review workflow. The broader roadmap is
in [workspace workflows](workspace-workflows.md). Automated verification uses
synthetic fixtures only.
