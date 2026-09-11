"""Opt-in, content-addressed batch-result reuse with verified output artifacts."""

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from .batch import run_batch
from .recipes import digest
from .samples import read_samples
from .vendor_info import vendor_identity


def cache_key(samples, recipe):
    records = read_samples(samples)
    paths = {Path(samples).resolve(), Path(recipe).resolve()}
    paths.update(Path(r["fcs_path"]) for r in records)
    paths.update(Path(r["compensation_path"]) for r in records if r.get("compensation_path"))
    inputs = {str(path): digest(path) for path in sorted(paths)}
    source = Path(__file__).parent
    implementation = {
        str(p.relative_to(source)): digest(p)
        for p in sorted(source.rglob("*.py"))
        if "_vendor" not in p.parts
    }
    implementation.update(
        {str(p.relative_to(source)): digest(p) for p in sorted((source / "assets").rglob("*")) if p.is_file()}
    )
    versions = {
        package: version(package)
        for package in [
            "agentflow-cytometry",
            "flowio",
            "flowutils",
            "numpy",
            "pandas",
            "pyarrow",
            "matplotlib",
            "scipy",
        ]
    }
    return hashlib.sha256(
        json.dumps([inputs, implementation, vendor_identity(), versions], sort_keys=True).encode()
    ).hexdigest()


def valid_cache(folder):
    try:
        index = json.loads((folder / "cache-files.json").read_text())
        actual = {
            str(p.relative_to(folder))
            for p in folder.rglob("*")
            if p.is_file() and p.name != "cache-files.json"
        }
        return actual == set(index) and all(
            digest(folder / name) == checksum for name, checksum in index.items()
        )
    except (OSError, ValueError, TypeError):
        return False


def run_cached(samples, recipe, output, cache):
    out, cache = Path(output).resolve(), Path(cache).resolve()
    if out.exists():
        raise ValueError("Output already exists; choose a new run directory")
    if cache == out or out in cache.parents:
        raise ValueError("Cache directory must be outside the output directory")
    key = cache_key(samples, recipe)
    entry = cache / key
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".agentflow-replay-", dir=out.parent))
    hit = valid_cache(entry)
    try:
        if hit:
            shutil.copytree(entry, temporary / "result", ignore=shutil.ignore_patterns("cache-files.json"))
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                run_batch(samples, recipe, temporary / "result")
        if cache_key(samples, recipe) != key:
            raise ValueError("Inputs or implementation changed during cached analysis")
        if out.exists():
            raise ValueError("Output appeared during analysis")
        if not hit and not entry.exists():
            cache.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".cache-", dir=cache))
            try:
                shutil.copytree(temporary / "result", staging / "result")
                index = {
                    str(p.relative_to(temporary / "result")): digest(p)
                    for p in (temporary / "result").rglob("*")
                    if p.is_file()
                }
                (staging / "result/cache-files.json").write_text(json.dumps(index, sort_keys=True))
                if not entry.exists():
                    (staging / "result").rename(entry)
            finally:
                shutil.rmtree(staging)
        if out.exists():
            raise ValueError("Output appeared during analysis")
        (temporary / "result").rename(out)
    finally:
        shutil.rmtree(temporary)
    print(json.dumps({"status": "complete", "output": str(out), "cache_hit": hit}))
    return pd.read_csv(out / "summary.csv")
