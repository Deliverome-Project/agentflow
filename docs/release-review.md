# Public release review

License for original Agentflow code: [MIT](../LICENSE). Author and maintainer:
Becca Carlson. This designation excludes bundled third-party components.
The top-level license excludes bundled third-party components; preserve their
licenses and copyright notices unchanged.

## Current status

The repository is public. Agentflow v0.10.0 (commit `19863da`) was released on
GitHub on 2026-10-28 and archived on Zenodo:

- Version DOI (v0.10.0): [10.5281/zenodo.23718422](https://doi.org/10.5281/zenodo.23718422)
- Concept DOI (all versions): [10.5281/zenodo.23718421](https://doi.org/10.5281/zenodo.23718421)

Zenodo archives are permanent. Publication does not resolve the open items
below, and this document records packaging scope and unresolved provenance,
not legal clearance.

## Open release items

These items were raised before the visibility change and remain open:

- Resolve legacy biexponential lookup-table provenance: the vendored
  `src/agentflow/_vendor/flowkit/_models/transforms/_wsp_transforms.py` describes a port from cytolib and earlier
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


## MVP candidate checks (2026-09-12)

Candidate revision: `4dc985d` (development branch; no public release).

- All 106 tests passed locally; Python 3.11/3.12, package and desktop CI passed.
- Wheel built from the source distribution and installed in an isolated Python
  3.12 environment. Headless smoke checks covered XML resources, Gating-ML
  round trips, bundled notices/fonts, and absence of a Qt dependency.
- Installed-wheel synthetic demo and three-sample batch run completed.
- Built wheel contains no FCS, workspace, CSV, Parquet or environment files.
- Gitleaks 8.30.1 scanned 37 reachable commits with no findings. PR title/body
  scan also passed. This is automated secret detection, not a guarantee that
  all historical narrative or hosting logs are suitable for public disclosure.
- No GitHub releases or uploaded Actions artifacts existed at inspection.

A private GitHub evaluation release v0.7.0 was subsequently created. That
immutable release predates the original-code MIT license addition. Its files and
tag have not been replaced.

These checks are a historical record of the 2026-09-12 candidate, not of
v0.10.0. The legacy biexponential provenance item above remains unresolved in
the public release.
