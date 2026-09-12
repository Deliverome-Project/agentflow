# Public release review

Proposed license for original Agentflow code: MIT. Author and maintainer:
Becca Carlson. This designation excludes bundled third-party components.
A top-level license has not yet been added. Preserve upstream notices unchanged.

Before changing repository visibility:

- Resolve legacy biexponential lookup-table provenance: the vendored
  `_models/transforms/_wsp_transforms.py` describes a port from cytolib and earlier
  TreeStar code. FlowKit declares BSD-3-Clause, while current cytolib declares
  AGPL-3.0. Determine the exact source version and applicable permissions; do
  not infer either infringement or permission from these labels alone.
  Keep source attribution intact pending clarification. Logicle is separate.
- Keep the three bundled ISAC XSD schemas unchanged under their embedded terms.
  Their distribution permission does not grant general modification rights.
- Keep bundled fonts under their SIL Open Font License and copyright notices.
- Review all reachable Git history, branches, PR text, release assets and CI logs
  for private experiment details or credentials. Removing a current document
  does not remove prior revisions.
- Upstream workspace compatibility identifiers and historical documentation
  still contain third-party product names. First-party presentation is neutral;
  do not claim the complete repository history is name-free.

The repository remains private while these release questions are resolved.
This document records packaging scope and unresolved provenance, not legal clearance.
