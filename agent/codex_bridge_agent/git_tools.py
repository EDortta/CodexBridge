from __future__ import annotations

import asyncio
from pathlib import Path


async def _git(project_root: Path, *args: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(project_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


async def collect_git_snapshot(project_root: Path, diff_max_chars: int) -> dict:
    branch_code, branch_out, _ = await _git(project_root, "branch", "--show-current")
    commit_code, commit_out, _ = await _git(project_root, "rev-parse", "HEAD")
    files_code, files_out, _ = await _git(project_root, "status", "--short")
    stat_code, stat_out, _ = await _git(project_root, "diff", "--stat")
    diff_code, diff_out, _ = await _git(project_root, "diff", "--no-ext-diff", "--binary")
    return {
        "branch": branch_out.strip() if branch_code == 0 else None,
        "commit": commit_out.strip() if commit_code == 0 else None,
        "modified_files": [line.strip() for line in files_out.splitlines()] if files_code == 0 else [],
        "diff_stat": stat_out.strip() if stat_code == 0 else "",
        "diff": diff_out[:diff_max_chars] if diff_code == 0 else "",
    }

