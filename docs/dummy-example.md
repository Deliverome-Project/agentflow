# DUMMY / EXAMPLE — downloaded Attune file

This walkthrough demonstrates software behavior using a downloaded file of
unknown experimental provenance. It is not a reviewed laboratory experiment.
Do not treat the draft populations as biological results.

```sh
uv sync --extra gui
uv run agentflow inspect "$HOME/Downloads/Attune NxT - A1.fcs"
uv run agentflow init "$HOME/Downloads/Attune NxT - A1.fcs" \
  --out local-examples/attune-dummy --example --compensation fcs \
  --gfp BL1-A --mscarlet YL2-A
uv run agentflow edit "$HOME/Downloads/Attune NxT - A1.fcs" \
  --recipe local-examples/attune-dummy/recipe.json
uv run agentflow run local-examples/attune-dummy/samples.csv \
  --recipe local-examples/attune-dummy/recipe.json \
  --out local-examples/attune-dummy/run-01
```

The BL1/YL2 assignments are only candidate channel labels for this dummy exercise.
The command does not establish that these dyes were used. This particular input
has no dye annotations confirming them, no identifiable viability measurement,
and no Cy5 detector. The editor leaves live/dead and Cy5 unmapped. It cannot
recover a measurement the instrument did not acquire. The file's embedded matrix
is identity, so its use does not change the signal values.

To rerun after saving revised gates, use `run-02` as a new output directory.
Open the generated `report.html`; keep all outputs local and uncommitted.

For a complete workflow including live/dead and Cy5, run `agentflow demo` as
shown in the main README. Its four single-stain controls have known synthetic
spillover. All of its samples and draft gate results remain explicitly dummy.
