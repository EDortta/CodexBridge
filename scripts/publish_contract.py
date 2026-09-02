#!/usr/bin/env python3
"""Publish the OpenAPI contract as a pinned, checksummed artifact.

Run explicitly, by whoever changed the contract:

    python3 scripts/publish_contract.py            # publish the current version
    python3 scripts/publish_contract.py --check    # verify; exit 1 on drift

Why this exists: `docs/api/README.md` §"Getting the contract to the mobile
repository" recorded the gap this closes. The document lived in this repository
and a consumer copied it by hand — nothing published it, nothing checksummed it,
and nothing detected that a copy had diverged. The route-drift gate protected the
*gateway ↔ document* pair and left the *document ↔ mobile client* pair, which is
the pair epic #1 exists for, unguarded. `info.version` was decoration: a client
could pin `1.6.0` and had no way to tell whether the bytes behind that number had
changed underneath it.

What it publishes, under `contract/`:

    contract/<version>/codex-bridge.openapi.yaml   byte-identical copy
    contract/<version>/manifest.json               version + sha256 of that copy
    contract/index.json                            every published version, and the latest

`EDortta/CodexBridgeMobile` pins a version by fetching that directory and
checking the digest — see `docs/api/testing.md`. Once published, a version
directory is **immutable**: `--check` recomputes every manifest digest, so
editing a published copy in place fails rather than silently rewriting what a
client already pinned.

**Nothing here carries a timestamp, a hostname or a user name.** That is not
tidiness: `--check` works by regenerating the artifact and comparing bytes, so a
field that changes between two runs of the same input would make the gate fire
on every run and be deleted within a week.

Publishing a *new* version is the same command. It writes a new directory and
leaves every previous one untouched, because a pin that can be rewritten is not
a pin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "docs" / "api" / "codex-bridge.openapi.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "contract"

#: Name the document keeps inside a published version directory. Kept equal to
#: the source filename so a consumer that already vendored the file by hand does
#: not have to rename anything when it switches to the pin.
DOCUMENT_NAME = "codex-bridge.openapi.yaml"

MANIFEST_NAME = "manifest.json"
INDEX_NAME = "index.json"

#: Written into every manifest so a consumer reading one knows which producer
#: shaped it. Bump it when the *layout* changes, never when the contract does.
ARTIFACT_FORMAT = 1


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version_key(version: str) -> tuple:
    """Sort key for a semver-ish string, falling back to text.

    A version that is not three integers sorts after every version that is,
    rather than raising: `index.json` describing an odd version badly is
    recoverable, refusing to publish it is not.
    """
    parts = version.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return (0, tuple(int(part) for part in parts), "")
    return (1, (), version)


def contract_version(source: Path) -> str:
    """`info.version` of the document at `source`.

    Read with the YAML parser rather than by regex: the version is the identity
    of the whole artifact, and a regex that matched `version:` inside a
    description block would publish a directory named after prose.
    """
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"{source} is not a YAML mapping")
    version = (document.get("info") or {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit(f"{source} has no info.version to publish")
    return version


def _published_versions(output: Path) -> list[str]:
    if not output.is_dir():
        return []
    versions = [
        entry.name
        for entry in output.iterdir()
        if entry.is_dir() and (entry / DOCUMENT_NAME).is_file()
    ]
    return sorted(versions, key=_version_key)


def _render_manifest(version: str, digest: str) -> str:
    return json.dumps(
        {
            "artifactFormat": ARTIFACT_FORMAT,
            "contractVersion": version,
            "document": DOCUMENT_NAME,
            "sha256": digest,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def _render_index(versions: list[str]) -> str:
    return json.dumps(
        {
            "artifactFormat": ARTIFACT_FORMAT,
            "latest": versions[-1] if versions else None,
            "versions": versions,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def publish(source: Path, output: Path) -> str:
    """Write the version directory and refresh the index. Returns the version.

    Writing is unconditional and byte-for-byte: an existing version directory is
    overwritten with the current document. That is deliberate and is exactly why
    `--check` also verifies **every** published version against its own manifest
    — the immutability of a pin is enforced by the check, not by this function
    refusing to write, because a refusal here would also block the legitimate
    case of re-publishing after an interrupted run.
    """
    version = contract_version(source)
    version_dir = output / version
    version_dir.mkdir(parents=True, exist_ok=True)

    document = version_dir / DOCUMENT_NAME
    shutil.copyfile(source, document)
    (version_dir / MANIFEST_NAME).write_text(
        _render_manifest(version, sha256_of(document)), encoding="utf-8"
    )
    (output / INDEX_NAME).write_text(
        _render_index(_published_versions(output)), encoding="utf-8"
    )
    return version


def _files_under(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def check(source: Path, output: Path) -> list[str]:
    """Everything wrong with the published artifact, in messages an operator can act on.

    Two independent failures, reported separately because the remedies differ:

    - the *current* version drifted from the document — regenerate;
    - a *previously published* version no longer matches its own manifest digest
      — that is a pinned artifact edited after the fact, and regenerating would
      destroy the evidence rather than fix it.
    """
    problems: list[str] = []

    if not output.is_dir():
        return [
            f"{output} does not exist: the contract has never been published. "
            "Run `python3 scripts/publish_contract.py`."
        ]

    version = contract_version(source)

    with tempfile.TemporaryDirectory() as tmp:
        expected_root = Path(tmp) / "contract"
        # Seed with the published versions so the regenerated index lists the
        # same set. Copying only the current version would make `index.json`
        # differ for every repository that has published more than one, which
        # is a gate firing on its own bookkeeping.
        for published in _published_versions(output):
            if published == version:
                continue
            shutil.copytree(output / published, expected_root / published)
        publish(source, expected_root)

        expected_files = _files_under(expected_root)
        actual_files = _files_under(output)

        for relative in sorted(expected_files - actual_files):
            problems.append(f"missing from {output}/: {relative}")
        for relative in sorted(actual_files - expected_files):
            problems.append(f"unexpected file in {output}/: {relative}")
        for relative in sorted(expected_files & actual_files):
            expected_bytes = (expected_root / relative).read_bytes()
            actual_bytes = (output / relative).read_bytes()
            if expected_bytes != actual_bytes:
                problems.append(f"stale: {relative} does not match the current document")

    if problems:
        problems.append(
            "The published contract is out of step with "
            f"{source.relative_to(REPO_ROOT) if source.is_relative_to(REPO_ROOT) else source}. "
            "Run `python3 scripts/publish_contract.py` and commit the result."
        )

    problems.extend(_digest_problems(output))
    return problems


def _digest_problems(output: Path) -> list[str]:
    """A published version whose bytes no longer match its recorded digest.

    This is the check that makes a pin mean something. A consumer that pinned
    `1.6.0` verified a digest once; if the file behind it can be edited while the
    manifest keeps the old number — or edited together with the manifest, which
    the version-control history still shows — the pin is decoration again.
    """
    problems: list[str] = []
    for version in _published_versions(output):
        manifest_path = output / version / MANIFEST_NAME
        if not manifest_path.is_file():
            problems.append(f"contract/{version}/ has no {MANIFEST_NAME}")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"contract/{version}/{MANIFEST_NAME} is not valid JSON: {exc}")
            continue
        recorded = manifest.get("sha256")
        actual = sha256_of(output / version / DOCUMENT_NAME)
        if recorded != actual:
            problems.append(
                f"contract/{version}/{DOCUMENT_NAME} was edited after publication: "
                f"manifest records {recorded}, file hashes to {actual}. A published "
                "version is what a client pinned; publish a new version instead of "
                "rewriting one."
            )
        if manifest.get("contractVersion") != version:
            problems.append(
                f"contract/{version}/{MANIFEST_NAME} names contractVersion "
                f"{manifest.get('contractVersion')!r}, but it lives in {version}/"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="OpenAPI document to publish. Defaults to the canonical contract.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory the pinned artifact is written to. Defaults to contract/.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift between the document and the published artifact; do not write.",
    )
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"No such contract document: {args.source}", file=sys.stderr)
        return 1

    if args.check:
        problems = check(args.source, args.output)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        print(f"Published contract is in sync with {args.source}.")
        return 0

    version = publish(args.source, args.output)
    print(f"Published contract {version} to {args.output}/{version}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
