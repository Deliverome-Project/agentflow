"""Inspect both distribution formats without extracting untrusted paths.

Secrets are separately scanned by Gitleaks; this guard catches common accidental
scientific outputs, local paths and private service links. It is not a data classifier.
"""
import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PRIVATE = re.compile(
    rb"(?:s3" rb"://(?!example(?:[-/]))|https://[^\s/]*notion\.(?:so|site)/[^\s]*[a-f0-9]{32}"
    rb"|[?&]X-Amz-(?:Credential|Signature)="
    rb"|/Users/[A-Za-z][^/\s]*/|deliverome-(?:raw|external|processed))", re.IGNORECASE
)
FORBIDDEN = {".fcs", ".wsp", ".parquet", ".csv", ".tsv", ".h5ad", ".pem", ".key"}
REQUIRED = ["LICENSE", "THIRD_PARTY_NOTICES.md", "agentflow/_vendor/flowkit/LICENSE",
            "agentflow/assets/fonts/Manrope-OFL.txt", "agentflow/assets/fonts/PlayfairDisplay-OFL.txt"]


def inspect_members(members):
    names = []
    for name, content in members:
        names.append(name)
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe archive path")
        if path.suffix.lower() in FORBIDDEN or path.name == ".env" or path.name.startswith(".env."):
            raise ValueError(f"Disallowed release file: {name}")
        if path.suffix not in {".ttf", ".woff", ".woff2"} and PRIVATE.search(content):
            raise ValueError(f"Private reference in release file: {name}")
    for required in REQUIRED:
        if not any(name == required or name.endswith("/" + required) for name in names):
            raise ValueError(f"Missing notice: {required}")


def main():
    artifacts = list(Path("dist").glob("*.whl")) + list(Path("dist").glob("*.tar.gz"))
    if not any(p.suffix == ".whl" for p in artifacts) or not any(p.name.endswith(".tar.gz") for p in artifacts):
        raise ValueError("Both wheel and source distribution are required")
    for path in artifacts:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                inspect_members((n, archive.read(n)) for n in archive.namelist() if not n.endswith("/"))
        else:
            with tarfile.open(path) as archive:
                members = archive.getmembers()
                if any(not (m.isfile() or m.isdir()) for m in members):
                    raise ValueError("Archive links and special files are not allowed")
                inspect_members((m.name, archive.extractfile(m).read()) for m in members if m.isfile())
        print(f"Release content check passed: {path.name}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
