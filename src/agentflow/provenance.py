"""Portable recipe snapshots with honest source and environment identity."""

import hashlib
import json
import subprocess
import tempfile
from importlib.metadata import distribution, distributions, version
from pathlib import Path

import yaml


def software_identity():
    source = Path(__file__).resolve().parent
    checksum = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".xsd", ".ttf", ".json"}:
            checksum.update(path.relative_to(source).as_posix().encode() + b"\0")
            checksum.update(path.read_bytes() + b"\0")
    commit, dirty = None, None
    root = source.parent.parent
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        try:
            commit = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
            dirty = bool(
                subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(root),
                        "status",
                        "--porcelain",
                        "--",
                        "src",
                        "pyproject.toml",
                        "uv.lock",
                    ],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            )
        except (OSError, subprocess.CalledProcessError):
            commit, dirty = None, None
    else:
        direct = distribution("agentflow-cytometry").read_text("direct_url.json")
        if direct:
            commit = json.loads(direct).get("vcs_info", {}).get("commit_id")
    return {
        "version": version("agentflow-cytometry"),
        "git_commit": commit,
        "working_tree_dirty": dirty,
        "source_sha256": checksum.hexdigest(),
    }


def save_snapshot(path, recipe, **context):
    """Write a derived YAML snapshot atomically; load_recipe accepts it for reruns."""
    document = {
        "snapshot_version": 1,
        "agentflow": software_identity(),
        "environment": {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
        "recipe": recipe,
        **context,
    }
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            yaml.safe_dump(
                json.loads(json.dumps(document, allow_nan=False)), handle, sort_keys=False, allow_unicode=True
            )
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
