# Working on agentflow

This is a standalone Python package for scientist-driven flow cytometry screens.
Keep batch execution headless and GUI imports optional. Use FlowKit's native
GatingStrategy for compensation, transformations and gate hierarchy execution.
Do not duplicate gate math in the GUI. Recipe parameters must be explicit and
shared across batch and editor paths. Never silently omit bad samples or infer
compensation when metadata is missing. Preserve detector labels and input
fingerprints. Counts use all events; display approximations must not change them.

Do not commit experimental FCS data, credentials, or analysis outputs. Use
synthetic fixtures for tests. Run `uv run ruff check .` and `uv run pytest -q`.
Work on dev and open a PR into main. Keep code independent of deliverome-analysis.
Document scientific assumptions and avoid claiming validation on real data when
only synthetic tests have run.

FlowKit is vendored at `src/agentflow/_vendor/flowkit`. Import it through
`from agentflow import flowkit`; do not add upstream FlowKit as a dependency.
Preserve its BSD license and notices, log changes in its AGENTFLOW.md, and avoid
bulk formatting the upstream tree. Keep FlowIO/FlowUtils external unless the
user requests otherwise. Verify wheel resources and license after vendoring edits.

Main requires a pull request, passing Python/package/desktop checks on an up-to-date branch,
and resolved review conversations. Protection applies to admins; force pushes and
deletion are disabled. No second reviewer is required while the project has one author.
