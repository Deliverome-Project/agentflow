"""Create a conventional recipe/sample-sheet folder without modifying FCS inputs."""

import shutil
import tempfile
from pathlib import Path

import pandas as pd

from .engine import prepare
from .workflow import scaffold


def create_project(files, output, compensation, example=False):
    files = [Path(path).resolve() for path in files]
    if not files or len({p.stem for p in files}) != len(files):
        raise ValueError("Choose FCS files with unique sample names")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new analysis folder name")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".agentflow-import-", dir=output.parent))
    try:
        recipe = scaffold(files[0], staging / "project", example=example, compensation=compensation)
        for path in files:
            prepare(path, recipe)
        pd.DataFrame([{"sample_id": p.stem, "fcs_path": str(p), "group": "Samples"} for p in files]).to_csv(
            staging / "project/samples.csv", index=False
        )
        (staging / "project").rename(output)
    finally:
        shutil.rmtree(staging)
    return output
