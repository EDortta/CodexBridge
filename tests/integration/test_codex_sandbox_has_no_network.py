"""Re-executable proof that `codex exec -s workspace-write` has no network --

WK-20260902-forge-binding, issue #79/#80 (PR B4). The whole architecture
decision behind keeping forge operations OUTSIDE the coding-agent sandbox
(`docs/architecture.md`'s "Isolamento e políticas", `docs/security.md`'s
"Caminhos rejeitados para uma operação de forge alcançar a rede") rests on
one empirical claim: `workspace-write` cannot reach the network. That claim
was tested by hand against the `devel3` host on 2026-09-01
(`docs/napkin-lessons.md`, same date) — and the SAME session found that
`runners/codex.py`'s own comments asserted `codex-cli 0.147.0` while the
binary actually installed was `0.151.0`, four versions ahead of what the
comment claimed to have verified. The behavior had not changed, but nobody
would have known that without re-testing; the comment alone was not
evidence, it was a claim with an expiry date nobody had checked.

This file is the fix for THAT gap, not a retest of one specific version: a
real, re-executable test that any future session can run against whatever
`codex` binary is actually installed, so a change in sandbox behavior is
discovered by a failing assertion here, not by trusting a comment that may
be several releases stale. `docs/napkin-lessons.md`'s own words for this:
"o teste tem de ser re-executável ... para que a próxima sessão descubra a
mudança por falha, e não por sorte."

Structure mirrors `test_codex_runner_real_process.py`'s own
`requires_real_codex` pattern exactly: gated behind `RUN_REAL_CODEX_TESTS=1`
(and the `codex` binary on PATH) so a default `pytest` run — and CI, which
has neither a logged-in `~/.codex` account nor guaranteed outbound network —
stays exactly as fast and hermetic as it always has. Run explicitly with:

    RUN_REAL_CODEX_TESTS=1 python3 -m pytest \
        tests/integration/test_codex_sandbox_has_no_network.py -v

Each enabled test makes at least one real network call to a live model
(codex itself), and the positive-control test additionally makes one real
network call to a public HTTP endpoint from THIS process, unsandboxed.

Last run against a real `codex` binary: not run as part of writing this PR
(no live-model call was made to author it -- the instruction below was
written to be deterministic and checked by reading `runners/codex.py`'s
own `-s`/`--sandbox` handling, not by executing it). The FIRST session that
runs this with `RUN_REAL_CODEX_TESTS=1` should update this line with the
date and the `codex --version` it ran against — that is the record this
file exists to keep re-executable, not a comment to trust on faith.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.codex_bridge_agent.codex_runner import CodexRunner
from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.codex import SANDBOX_WORKSPACE_WRITE


_REASON = (
    "real-codex tests are opt-in: set RUN_REAL_CODEX_TESTS=1 to spawn a real "
    "`codex` subprocess (needs the binary on PATH, a logged-in ~/.codex, and "
    "network access to a live model)."
)
requires_real_codex = pytest.mark.skipif(
    os.environ.get("RUN_REAL_CODEX_TESTS") != "1" or shutil.which(AgentSettings().codex_bin) is None,
    reason=_REASON,
)

# A short, deterministic network probe: a real public HTTP endpoint, a tight
# timeout so a hung sandbox does not stall the whole test, and a fixed output
# file so the assertion below reads a file `codex` wrote rather than parsing
# its own free-text summary of what happened (`codex exec`'s final message is
# model-authored prose, not a stable contract to assert against).
_PROBE_URL = "https://example.com"
_PROBE_RESULT_FILE = "network_probe_result.txt"
_PROBE_COMMAND = f"curl -sS --max-time 5 -o /dev/null -w '%{{http_code}}' {_PROBE_URL}"

_INSTRUCTION = (
    f"Run exactly this shell command: `{_PROBE_COMMAND}` -- capture BOTH its stdout "
    f"and its exit code, then write a file named {_PROBE_RESULT_FILE} in the current "
    "directory containing exactly two lines: the exit code on the first line, and the "
    "captured stdout on the second line (empty if there was none). Do not retry the "
    "command, do not attempt any other network call, and do not modify any other file. "
    "Then stop."
)


def _init_scratch_repo(root: Path) -> None:
    """Same disposable, throwaway git repo `test_codex_runner_real_process.py`

    uses -- never a real project, never given a remote."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "codexbridge-test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "codexbridge-test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "README.md").write_text("Scratch fixture repo for the sandbox-network test.\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "initial commit"], cwd=root, check=True, env=env)


async def _collect_logs(_name: str, _line: str) -> None:
    return None


def _read_probe_result(root: Path) -> tuple[str, str]:
    result_path = root / _PROBE_RESULT_FILE
    assert result_path.is_file(), (
        f"codex never wrote {_PROBE_RESULT_FILE} -- either it refused to run the probe "
        "command at all, or the instruction was not followed. Check the raw run output."
    )
    lines = result_path.read_text(encoding="utf-8").splitlines()
    exit_code = lines[0].strip() if lines else ""
    stdout = lines[1].strip() if len(lines) > 1 else ""
    return exit_code, stdout


@requires_real_codex
@pytest.mark.asyncio
async def test_workspace_write_sandbox_has_no_network(tmp_path: Path) -> None:
    """THE property `docs/security.md`'s rejected-paths subsection and

    `docs/architecture.md`'s forge-binding section both depend on:
    `-s workspace-write` cannot reach the network. `curl` inside the sandbox
    must fail to connect -- a non-zero/non-`000`-distinguishable exit code
    from `curl`, never the HTTP status a real connection would have
    produced. `test_network_works_outside_the_sandbox_on_this_host` below is
    the positive control this assertion is meaningless without: without it,
    a green result here could just as easily mean "this host has no
    internet at all" as "the sandbox blocked it".
    """
    _init_scratch_repo(tmp_path)
    runner = CodexRunner(AgentSettings())

    result = await runner.run_task(
        task_id="sandbox-network-probe-1",
        project_root=tmp_path,
        instruction=_INSTRUCTION,
        timeout_seconds=90,
        continue_session_id=None,
        send_log=_collect_logs,
        sandbox=SANDBOX_WORKSPACE_WRITE,
    )
    assert result["return_code"] == 0, "the codex process itself must exit cleanly even though the probe failed"

    exit_code, stdout = _read_probe_result(tmp_path)
    # `curl`'s own exit code for "could not connect / resolve / reach the
    # host" is never `0` -- `0` means the request round-tripped, which would
    # mean the sandbox has network. `-w '%{http_code}'` alone is not enough:
    # curl prints `000` for a failed connection too, but a `0` (or non-`0`)
    # EXIT CODE is curl's own, unambiguous verdict on whether the transfer
    # happened at all, so that is what this assertion is built on.
    assert exit_code != "0", (
        f"curl exit code was {exit_code!r} (stdout {stdout!r}) -- the workspace-write "
        "sandbox appears to have network access, which contradicts the architecture "
        "decision this test exists to keep honest. Re-read docs/security.md's "
        "'Caminhos rejeitados' subsection before changing anything that depends on this."
    )


@requires_real_codex
def test_network_works_outside_the_sandbox_on_this_host(tmp_path: Path) -> None:
    """Positive control for the test above, per docs/napkin-lessons.md's

    2026-09-01 lesson ("sem ele, um teste verde provaria só que nada
    rodou"): the EXACT SAME probe command, run directly by this test
    process -- no `codex`, no sandbox at all -- must succeed. If this
    fails, the host itself has no usable network right now, and the sandbox
    test above proves nothing regardless of its own result.
    """
    completed = subprocess.run(
        ["curl", "-sS", "--max-time", "5", "-o", os.devnull, "-w", "%{http_code}", _PROBE_URL],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"the unsandboxed control call itself failed (exit {completed.returncode}, "
        f"stderr {completed.stderr!r}) -- this host has no usable network right now; "
        "the sandbox test's result cannot be trusted until this passes."
    )
