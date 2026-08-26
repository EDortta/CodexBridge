"""The pinned contract artifact `EDortta/CodexBridgeMobile` consumes.

`test_openapi_document.py` guards the *gateway ↔ document* pair. This file
guards the *document ↔ published artifact* pair, which is the half
`docs/api/README.md` §"Getting the contract to the mobile repository" recorded as
unguarded: the document lived here, a consumer copied it by hand, nothing
checksummed it, and `info.version` was a number a client could pin without any
guarantee that the bytes behind it would still be the same tomorrow.

Two failures, deliberately kept apart because the remedies are opposite:

- the published copy is **behind** the document — regenerate it
  (`python3 scripts/publish_contract.py`);
- a **previously published** version no longer hashes to its own manifest — a
  pinned artifact was edited after the fact, and regenerating would erase the
  evidence rather than fix anything.

The script is exercised as a subprocess, the same way
`tests/unit/test_apply_migrations.py` exercises the migration runner: the thing
CI runs is the thing under test, argument parsing and exit code included.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "publish_contract.py"
SPEC_PATH = REPO_ROOT / "docs" / "api" / "codex-bridge.openapi.yaml"
CONTRACT_DIR = REPO_ROOT / "contract"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_the_publisher_exists_and_runs() -> None:
    """If the script moves, every other test here would pass vacuously."""
    assert SCRIPT.is_file(), f"the contract publisher is missing: {SCRIPT}"
    assert run("--help").returncode == 0


def test_the_published_artifact_matches_the_current_document() -> None:
    """A merged contract change that never reached `contract/` is drift.

    This is the acceptance criterion "pull requests fail when implementation
    diverges from the published contract", on the publication side: the gateway
    and the document are already bound to each other, and this binds the
    document to the copy the mobile repository actually downloads.
    """
    result = run("--check")
    assert result.returncode == 0, (
        "the published contract is out of step with the document:\n"
        f"{result.stderr}{result.stdout}"
    )


def test_the_current_version_is_published(spec: dict) -> None:
    """`info.version` must name a directory a client can fetch.

    Asserted separately from `--check` so that a publisher which silently
    stopped writing version directories fails here by name rather than as a
    confusing byte diff.
    """
    version = spec["info"]["version"]
    published = CONTRACT_DIR / version / "codex-bridge.openapi.yaml"
    assert published.is_file(), (
        f"the contract is at {version} and nothing is published under "
        f"contract/{version}/. Run `python3 scripts/publish_contract.py`."
    )


def test_the_index_names_the_current_version_as_latest(spec: dict) -> None:
    """The pointer a consumer follows when it has not pinned yet."""
    index = json.loads((CONTRACT_DIR / "index.json").read_text(encoding="utf-8"))
    assert index["latest"] == spec["info"]["version"]
    assert spec["info"]["version"] in index["versions"]


def test_a_published_version_is_byte_identical_to_the_document(spec: dict) -> None:
    """Not "equivalent YAML" — identical bytes.

    A consumer verifies a SHA-256. Re-serialising the document on the way out
    would produce a file that parses the same and hashes differently on every
    PyYAML upgrade, so the digest would stop identifying the content and start
    identifying the toolchain.
    """
    version = spec["info"]["version"]
    published = CONTRACT_DIR / version / "codex-bridge.openapi.yaml"
    assert published.read_bytes() == SPEC_PATH.read_bytes()


def test_every_published_version_hashes_to_its_manifest() -> None:
    """The property that makes a pin worth pinning.

    Re-implemented here rather than delegated to `--check`, because a bug in the
    script's own digest comparison would make `--check` green and this test is
    what says so independently.
    """
    import hashlib

    versions = sorted(path for path in CONTRACT_DIR.iterdir() if path.is_dir())
    assert versions, "no contract version is published at all"
    for version_dir in versions:
        manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
        document = version_dir / "codex-bridge.openapi.yaml"
        digest = hashlib.sha256(document.read_bytes()).hexdigest()
        assert manifest["sha256"] == digest, (
            f"contract/{version_dir.name}/ was edited after publication: the "
            f"manifest records {manifest['sha256']}, the file hashes to {digest}. "
            "Publish a new version rather than rewriting one a client has pinned."
        )
        assert manifest["contractVersion"] == version_dir.name


# --------------------------------------------------------------------------
# The gate has to be able to fail, or it is decoration
# --------------------------------------------------------------------------


def _isolated_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A copy of the document and the published artifact, safe to corrupt."""
    source = tmp_path / "codex-bridge.openapi.yaml"
    shutil.copyfile(SPEC_PATH, source)
    output = tmp_path / "contract"
    shutil.copytree(CONTRACT_DIR, output)
    return source, output


def test_check_reports_a_document_that_moved_ahead_of_the_artifact(tmp_path: Path) -> None:
    """Change the document, do not republish: the check must name the stale file."""
    source, output = _isolated_tree(tmp_path)
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "summary: Contract-first HTTP API consumed by CodexBridgeMobile.",
            "summary: Something else entirely.",
        ),
        encoding="utf-8",
    )

    result = run("--check", "--source", str(source), "--output", str(output))
    assert result.returncode == 1
    assert "stale" in result.stderr
    assert "codex-bridge.openapi.yaml" in result.stderr
    assert "scripts/publish_contract.py" in result.stderr


def test_check_reports_a_published_version_edited_after_the_fact(tmp_path: Path) -> None:
    """Rewriting a pinned version is the failure the digest exists to catch."""
    source, output = _isolated_tree(tmp_path)
    version = yaml.safe_load(source.read_text(encoding="utf-8"))["info"]["version"]
    published = output / version / "codex-bridge.openapi.yaml"
    published.write_text(published.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    result = run("--check", "--source", str(source), "--output", str(output))
    assert result.returncode == 1
    assert "edited after publication" in result.stderr
    assert version in result.stderr


def test_check_reports_a_contract_that_was_never_published(tmp_path: Path) -> None:
    source = tmp_path / "codex-bridge.openapi.yaml"
    shutil.copyfile(SPEC_PATH, source)

    result = run("--check", "--source", str(source), "--output", str(tmp_path / "nowhere"))
    assert result.returncode == 1
    assert "never been published" in result.stderr


def test_publishing_a_new_version_leaves_the_old_one_untouched(tmp_path: Path) -> None:
    """A pin survives the next release, or it was never a pin.

    Publishing `9.9.9` must add a directory and change nothing inside the
    version a client already downloaded — including its digest.
    """
    source, output = _isolated_tree(tmp_path)
    current = yaml.safe_load(source.read_text(encoding="utf-8"))["info"]["version"]
    before = (output / current / "codex-bridge.openapi.yaml").read_bytes()
    before_manifest = (output / current / "manifest.json").read_bytes()

    source.write_text(
        source.read_text(encoding="utf-8").replace(f"version: {current}", "version: 9.9.9", 1),
        encoding="utf-8",
    )
    result = run("--source", str(source), "--output", str(output))
    assert result.returncode == 0, result.stderr

    assert (output / current / "codex-bridge.openapi.yaml").read_bytes() == before
    assert (output / current / "manifest.json").read_bytes() == before_manifest
    assert (output / "9.9.9" / "codex-bridge.openapi.yaml").is_file()

    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    assert index["latest"] == "9.9.9"
    assert current in index["versions"]

    # And the whole artifact is self-consistent again afterwards.
    assert run("--check", "--source", str(source), "--output", str(output)).returncode == 0


def test_publishing_is_deterministic(tmp_path: Path) -> None:
    """Two runs over one input produce identical bytes.

    `--check` compares a regenerated artifact against the committed one, so a
    timestamp, a hostname or a dict iteration order in the output would make the
    gate fire on every run — and a gate that cries wolf is a gate that gets
    deleted rather than obeyed.
    """
    source = tmp_path / "codex-bridge.openapi.yaml"
    shutil.copyfile(SPEC_PATH, source)
    first, second = tmp_path / "a", tmp_path / "b"

    assert run("--source", str(source), "--output", str(first)).returncode == 0
    assert run("--source", str(source), "--output", str(second)).returncode == 0

    files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    assert files
    for relative in files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes(), (
            f"{relative} differs between two runs over the same document"
        )
