"""Build reviewable sample sheets from acquired files and agent-authored annotations."""

import csv
import json
import shutil
import tempfile
from pathlib import Path

import yaml

from . import flowkit
from .acquisition import instrument_provenance
from .recipes import digest


def draft_sample_sheet(folder, output, annotations=None):
    folder, output = Path(folder).resolve(), Path(output).resolve()
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".fcs")
    if not files:
        raise ValueError("No FCS files found")
    if output.exists():
        raise ValueError("Output already exists; choose a new sample-sheet folder")
    document = yaml.safe_load(Path(annotations).read_text()) if annotations else {"samples": []}
    if not isinstance(document, dict) or not isinstance(document.get("samples"), list):
        raise TypeError("Annotations require a samples list")
    mapped = {}
    names = {p.relative_to(folder).as_posix() for p in files}
    reserved = {"fcs_path", "input_sha256", "annotation_source", "metadata_reviewed"}
    for entry in document["samples"]:
        if not isinstance(entry, dict) or entry.get("file") not in names or entry["file"] in mapped:
            raise ValueError("Each annotation must identify one unique exact relative FCS filename")
        metadata = entry.get("metadata", {})
        if not isinstance(metadata, dict) or reserved.intersection(metadata):
            raise ValueError("Annotation metadata must be a mapping without reserved provenance fields")
        if any(
            not isinstance(k, str) or k.startswith("fcs:") or isinstance(v, (list, dict))
            for k, v in metadata.items()
        ):
            raise ValueError("Sample-sheet metadata fields must have scalar values")
        if not isinstance(entry.get("reviewed", False), bool):
            raise TypeError("Annotation reviewed must be true or false")
        mapped[entry["file"]] = entry
    rows, instruments = [], {}
    for path in files:
        relative = path.relative_to(folder).as_posix()
        entry = mapped.get(relative, {})
        before = digest(path)
        sample = flowkit.Sample(str(path))
        if digest(path) != before:
            raise ValueError(f"Input changed while reading {relative}")
        instrument = instrument_provenance(sample)
        row = {
            "sample_id": str(Path(relative).with_suffix("")),
            "fcs_path": str(path),
            "group": "",
            "condition": "",
            "well": "",
            "plate": "",
            "biological_replicate": "",
            **entry.get("metadata", {}),
            "input_sha256": before,
            "metadata_reviewed": entry.get("reviewed", False),
            "annotation_source": entry.get("source_url", ""),
        }
        for key in ["instrument", "serial_number", "acquisition_date", "acquisition_software"]:
            row["fcs:" + key] = instrument[key] or ""
        rows.append(row)
        instruments[relative] = instrument
    if any(not str(r["sample_id"]).strip() for r in rows) or len({str(r["sample_id"]) for r in rows}) != len(
        rows
    ):
        raise ValueError("Sample IDs must be nonempty and unique")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".sample-sheet-", dir=output.parent))
    try:
        with (staging / "samples.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
            writer.writeheader()
            writer.writerows(rows)
        (staging / "acquisition.json").write_text(json.dumps(instruments, indent=2) + "\n")
        (staging / "annotations.yaml").write_text(yaml.safe_dump(document, sort_keys=False))
        (staging / "README.md").write_text(
            "# Draft sample sheet\n\nReview sample identities, groups, controls, and plate assignments before analysis. "
            "Unspecified biological fields remain blank. Annotation links record evidence; "
            "they do not certify its correctness. FCS-reported acquisition values are preserved separately "
            "from user annotations in acquisition.json and fcs: columns.\n"
        )
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return rows
