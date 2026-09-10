"""Record the exact vendored engine used, including local modifications."""

import hashlib
import json
from pathlib import Path

from ._vendor import flowkit


def vendor_identity():
    root = Path(flowkit.__file__).parent
    upstream = json.loads((root / "UPSTREAM.json").read_text())
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".xsd"):
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return {
        "distribution": "vendored",
        "upstream_version": upstream["version"],
        "upstream_commit": upstream["commit"],
        "source_sha256": digest.hexdigest(),
    }
