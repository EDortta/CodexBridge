"""Runs the `gh` CLI as a subprocess, and only that -- the forge-side sibling

of `agent/codex_bridge_agent/git_tools.run_git`. Same shape, same
reasoning: `asyncio.create_subprocess_exec` with an argv LIST (never a shell
string, so nothing here can be reinterpreted by a shell), a timeout that
always applies, and stdout/stderr captured and decoded rather than left to
inherit the executor's own streams.

`run_gh` additionally owns the one thing `run_git` never had to: resolving
the `GH_TOKEN` credential and injecting it into the subprocess's own `env=`,
nowhere else. Two guards make that safe:

  1. `resolve_gh_token` refuses unless the credential path is a SYMLINK whose
     resolved target sits outside `project_root` -- never a regular file
     inside the tree the coding agent (running in this same project, in its
     own sandboxed session) can read. The convention this mirrors already
     exists in this repo: `.credentials/store` here is itself a symlink to
     `~/.config/credentials/personal`, and `.gitignore` ignores
     `.credentials/*` wholesale. If the token's bytes never exist inside the
     tree, no path the coding agent can read ever holds them.
  2. `git_delivery._is_forbidden_path` already refuses to stage or commit
     anything with `.credentials` in its path (`git_delivery.py:56-80`,
     pre-existing, `AGENTS.md` §7) -- so even if guard 1 above were somehow
     bypassed, the token could not travel from working tree to commit. This
     module does not re-implement that guard; it relies on it staying in
     place, and `tests/unit/test_git_delivery.py` now names the case
     (`.credentials/github-token`) explicitly as a defense of this feature so
     it is not mistaken for dead weight and removed later.

`GH_ENV_ALLOWLIST` is a third, disjoint env allowlist alongside
`runners/codex.py`'s `CODEX_ENV_ALLOWLIST` and `runners/claude.py`'s
`CLAUDE_ENV_ALLOWLIST` (council finding F08: env custody must never be
unioned across engines). `GH_TOKEN` belongs on exactly this allowlist and no
other -- `tests/unit/test_runner_registry.py::
test_no_registered_engines_env_allowlist_overlaps_another` is extended in
this PR to prove it never leaks onto a runner's.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from shared.security import filtered_environment


# `HOME`/`PATH` so `gh` itself can run and find its own config; `GH_TOKEN` is
# never present in `os.environ` (nothing in this codebase sets it globally --
# see `config.py`'s own docstring on `forge_credential_relative_path`), it is
# injected explicitly by `run_gh` below, once, per operation.
GH_ENV_ALLOWLIST = frozenset({"HOME", "PATH", "GH_TOKEN"})


@dataclass(frozen=True)
class GhResult:
    """Mirrors `run_git`'s `(code, stdout, stderr)` tuple, plus the one
    failure mode `run_git` has no equivalent of: a credential that fails the
    symlink-outside-repo guard before any subprocess is ever spawned.
    `returncode` is `None` exactly when `refused_reason` is set -- `gh` never
    ran.
    """

    returncode: int | None
    stdout: str
    stderr: str
    refused_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.refused_reason is None and self.returncode == 0


def resolve_gh_token(project_root: Path, credential_relative_path: str) -> tuple[str | None, str | None]:
    """Reads the GH token, enforcing the symlink-outside-repo guard.

    Returns `(token, None)` on success, `(None, reason)` on refusal.
    Deliberately synchronous and side-effect-free beyond the read -- callable
    on its own from a test that wants to check the guard without spawning a
    fake `gh` at all.
    """
    credential_path = project_root / credential_relative_path
    if not credential_path.exists() and not credential_path.is_symlink():
        return None, "forge_credential_missing"
    if not credential_path.is_symlink():
        # A regular file living inside the tree: exactly what this guard
        # exists to refuse. `.is_symlink()` is checked, not `.is_file()` --
        # a symlink whose target is also a regular file must still pass
        # through the branch below so its resolved target gets checked
        # against `project_root`.
        return None, "forge_credential_must_be_symlink_outside_repo"
    resolved_target = credential_path.resolve()
    resolved_root = project_root.resolve()
    if resolved_target == resolved_root or resolved_root in resolved_target.parents:
        return None, "forge_credential_must_be_symlink_outside_repo"
    if not resolved_target.is_file():
        return None, "forge_credential_target_missing"
    token = resolved_target.read_text(encoding="utf-8").strip()
    if not token:
        return None, "forge_credential_empty"
    return token, None


async def run_gh(
    project_root: Path,
    *args: str,
    gh_bin: str,
    credential_relative_path: str,
    timeout_seconds: float,
) -> GhResult:
    """Runs one `gh` subcommand in `project_root`, capturing stdout/stderr.

    `args` becomes `gh`'s argv verbatim, as a list -- callers in `github.py`
    build that list from validated, pattern-checked fields
    (`shared.protocol.REPO_IDENTITY_PATTERN`) and from temp-file paths this
    package itself creates, never from raw title/body text placed at a flag
    position. No shell is ever involved, so nothing here can be reinterpreted
    by one.
    """
    token, refused_reason = resolve_gh_token(project_root, credential_relative_path)
    if refused_reason is not None:
        return GhResult(returncode=None, stdout="", stderr="", refused_reason=refused_reason)

    env = filtered_environment(GH_ENV_ALLOWLIST)
    env["GH_TOKEN"] = token or ""

    process = await asyncio.create_subprocess_exec(
        gh_bin,
        *args,
        cwd=str(project_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return GhResult(returncode=124, stdout="", stderr="timed out waiting for gh")
    return GhResult(
        returncode=process.returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )
