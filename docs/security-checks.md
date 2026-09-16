# Dependency and release checks

Agentflow is in active development. These checks reduce common supply-chain and
accidental-publication risks; they do not establish that a package is trustworthy.

## Seven-day quarantine

`[tool.uv] exclude-newer = "7 days"` applies when resolving dependencies. CI also
sets `UV_EXCLUDE_NEWER` for isolated wheel installation and build resolution.
The committed lock includes development, GUI, build and security-tool groups.
CI installs the locked build group and builds without isolated dependency resolution.

Before installing project dependencies, `python3 scripts/check_dependency_age.py`
checks every registry package and every wheel/source artifact recorded in `uv.lock`
against PyPI's SHA-256 digests and upload timestamps. A later-uploaded wheel must
age independently of its release's first file. Missing metadata, network failures,
yanked artifacts and unapproved sources fail the check; retry after an outage.
The local editable Agentflow package is the only source exception.

This scans the whole lock, including alternate Python/platform versions, rather
than trusting a previous successful check. It does not automatically constrain
someone else's `pip install`; consumers must apply their own installation policy.
GitHub Actions, OS packages and Python interpreters are outside the PyPI age check.
Actions are pinned to commit hashes; uv and Gitleaks versions are pinned, and the
Gitleaks download is verified against a committed SHA-256 checksum.

## Automated checks

- Every push and PR: dependency age, lint, scientific tests, wheel installation,
  release contents, credential scanning and known-vulnerability auditing.
- Weekly and manually: repeat age, vulnerability and secret checks on the default
  branch, including newly published vulnerability advisories.
- Python 3.11 and 3.12 advisory checks cover runtime, GUI, development, build and
  audit dependencies applicable to each interpreter. No dependencies are installed
  by the advisory scanner itself. A scanner failure blocks the job.
- Linux and macOS run the desktop tests with Qt's offscreen backend. This exercises
  widgets and gate interactions, but cannot replace manual on-screen usability QA.
- Gitleaks scans reachable Git history and the built release archives with redacted
  output. Release-content checks reject common experimental data extensions,
  credential files, private storage/Notion links and personal local paths, and
  require original-code, vendored-code and font notices in both wheel and source
  distributions. Heuristic privacy checks cannot recognize every sensitive detail.

Run locally:

```sh
python3 scripts/check_dependency_age.py
uv sync --locked --all-groups --extra gui
uv run --locked ruff check .
QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg uv run --locked --extra gui pytest -q
uv build --no-build-isolation
uv run --locked python scripts/check_release_contents.py
uv export --locked --all-groups --all-extras --no-emit-project --no-hashes -o /tmp/agentflow-audit.txt
uv run --locked --group security pip-audit --strict --no-deps --disable-pip -r /tmp/agentflow-audit.txt
```

When an update fails: keep the previous known-good version, or investigate the
specific advisory/artifact. Do not add broad ignores or bypass checks to make a
release pass. An urgent security update inside the quarantine needs a documented,
narrowly scoped policy decision, not an automatic exemption.

Main protection requires the original Python/package/desktop jobs plus
`dependency-security (3.11)`, `dependency-security (3.12)`, `secrets`, and
`desktop-macos`. Up-to-date branches and resolved conversations remain required;
admin enforcement, force-push and deletion restrictions are unchanged.
