# Scientific credits and citation guidance

When publishing papers, preprints, or reports using Agentflow results, cite the
original FlowKit paper below as well as identifying Agentflow and the version or
commit used. Agentflow's workflow and interface build on FlowKit's analysis
engine; the original methods and software credit belongs to its authors.

White S, Quinn J, Enzor J, Staats J, Mosier SM, Almarode J, Denny TN, Weinhold KJ, Ferrari G, Chan C (2021). FlowKit: A Python toolkit for integrated manual and automated cytometry analysis workflows. Frontiers in Immunology 12:768541. https://doi.org/10.3389/fimmu.2021.768541

Agentflow bundles a modified FlowKit 1.3.2 from commit
`f2159043b6a56e527d4baacf97490caf8354618e`. See
[third-party notices](THIRD_PARTY_NOTICES.md) for copyright and licensing and
[the modification log](src/agentflow/_vendor/flowkit/AGENTFLOW.md) for changes.
FlowIO and FlowUtils remain external dependencies and retain their own authorship.
Use the run provenance for the versions actually used. No upstream endorsement
of Agentflow or its modifications is implied.

## Suggested methods wording

Flow cytometry data were analyzed with Agentflow [version/commit], using its
modified FlowKit 1.3.2 engine (White et al., 2021). Gate definitions, compensation,
transformations, and software provenance were retained with the run outputs.

Replace the version placeholder and describe the actual reviewed analysis.
Each batch HTML report includes the FlowKit citation so it remains visible when
the standalone report is shared.
