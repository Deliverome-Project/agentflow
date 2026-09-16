"""Fail closed unless every locked PyPI artifact is at least seven days old.

Uses only the standard library, before installing project dependencies. Checks
all platform/Python variants and optional groups, not just the active environment.
"""
import json
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen


def check_package(package, now, fetch=None):
    source = package["source"]
    if source == {"editable": "."}:
        return
    if source != {"registry": "https://pypi.org/simple"}:
        raise ValueError("Unapproved dependency source")
    name, version = package["name"], package["version"]
    if fetch is None:
        def fetch(url):
            with urlopen(url, timeout=30) as response:
                return json.load(response)
    metadata = fetch(f"https://pypi.org/pypi/{name}/{version}/json")
    files = {f["digests"]["sha256"]: f for f in metadata["urls"]}
    artifacts = package.get("wheels", []) + ([package["sdist"]] if "sdist" in package else [])
    if not artifacts:
        raise ValueError("No locked artifacts")
    for artifact in artifacts:
        algorithm, digest = artifact["hash"].split(":", 1)
        if algorithm != "sha256" or digest not in files:
            raise ValueError("Artifact hash unavailable from PyPI")
        record = files[digest]
        if record.get("yanked"):
            raise ValueError("Locked artifact is yanked")
        uploaded = datetime.fromisoformat(record["upload_time_iso_8601"])
        if now - uploaded < timedelta(days=7):
            raise ValueError("Locked artifact is less than seven days old")


def main():
    lock = tomllib.loads(Path("uv.lock").read_text())
    now = datetime.now(UTC)
    def check(package):
        try:
            check_package(package, now)
            return None
        except (OSError, ValueError, KeyError, TypeError) as error:
            # Do not print network responses or credential-bearing source URLs.
            return f"{package['name']}=={package['version']}: verification failed ({type(error).__name__})"
    with ThreadPoolExecutor(max_workers=8) as pool:
        errors = list(filter(None, pool.map(check, lock["package"])))
    for error in errors:
        print(error)
    print(f"Checked {len(lock['package'])} locked packages; {len(errors)} failures.")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
