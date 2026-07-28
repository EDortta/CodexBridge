from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest


TASKS_BY_STATE = Gauge("codex_bridge_tasks_by_state", "Tasks by state", ["state"])
CONNECTED_EXECUTORS = Gauge("codex_bridge_connected_executors", "Connected executors")
TASK_DURATION_SECONDS = Histogram("codex_bridge_task_duration_seconds", "Task duration seconds")
TASK_ERRORS = Counter("codex_bridge_task_errors_total", "Codex task errors", ["reason"])


def render_metrics() -> bytes:
    return generate_latest()

