#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ "$(git branch --show-current)" != "development" ]]; then
  echo "ERROR: run this from branch development" >&2
  exit 2
fi

mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-devel3-issue51-regression-fix.txt"
exec > >(tee "$RESULT") 2>&1

echo "== issue #51 regression repair =="
echo "head_before=$(git rev-parse HEAD)"
git status --short

python3 - <<'PY'
from pathlib import Path

# A) Keep the already-published /delivery response backward-compatible.
# Completion evidence remains durable in mission.attempt_completed payloads;
# #51 must not silently change issue #69's response shape.
p = Path("gateway/app/api/routes/missions.py")
s = p.read_text()
imp = '''from gateway.app.services.mission_completion import (\n    build_completion_evidence,\n    completion_policy_from_project_config,\n    evaluate_completion_gate,\n)\n'''
s = s.replace(imp, "")
start = s.find('def _completion_contract_dto(')
if start != -1:
    end = s.find('@router.get("/missions/{mission_id}/delivery", tags=["missions"])', start)
    if end == -1:
        raise SystemExit("missions.py: completion helper end anchor missing")
    s = s[:start] + s[end:]
old = '''    task = await store.get_mission_active_task(session, mission)\n    project = await session.get(ProjectModel, mission.project_id)\n    response.headers["Cache-Control"] = "no-store"\n    body = _delivery_evidence_dto(mission, task)\n    body["completion"] = _completion_contract_dto(\n        mission, task, project.config_json if project is not None else None\n    )\n    return body\n'''
new = '''    task = await store.get_mission_active_task(session, mission)\n    response.headers["Cache-Control"] = "no-store"\n    return _delivery_evidence_dto(mission, task)\n'''
if old in s:
    s = s.replace(old, new, 1)
p.write_text(s)

# B) A Mission held in reviewing because the completion gate failed must be
# restartable. restart_finished_task legitimately moves it back to queued or
# waiting_executor for another attempt.
p = Path("gateway/app/services/mission_types.py")
s = p.read_text()
old = '''    MissionState.REVIEWING.value: frozenset(\n        {MissionState.RUNNING.value, MissionState.WAITING_HUMAN.value, MissionState.COMPLETED.value, MissionState.FAILED.value, MissionState.CANCELLED.value}\n    ),\n'''
new = '''    MissionState.REVIEWING.value: frozenset(\n        {\n            MissionState.RUNNING.value,\n            MissionState.QUEUED.value,\n            MissionState.WAITING_EXECUTOR.value,\n            MissionState.WAITING_HUMAN.value,\n            MissionState.COMPLETED.value,\n            MissionState.FAILED.value,\n            MissionState.CANCELLED.value,\n        }\n    ),\n'''
if old not in s:
    raise SystemExit("mission_types.py: REVIEWING transition anchor missing")
s = s.replace(old, new, 1)
p.write_text(s)

# C) Test completion evidence where it is durably stored: the Mission event.
# Do not couple #51 to the older #69 delivery DTO.
p = Path("tests/integration/test_issue_resolution.py")
s = p.read_text()
old = '''    detail = api.get(f"/api/v1/missions/{body['id']}", headers=auth(ALICE_TOKEN)).json()\n    assert detail["state"] == "completed"\n    delivery = api.get(\n        f"/api/v1/missions/{body['id']}/delivery", headers=auth(ALICE_TOKEN)\n    ).json()\n    assert delivery["completion"]["evidence"]["validated"] is True\n    assert delivery["completion"]["evidence"]["delivered"] is True\n    assert delivery["completion"]["gate"] == {"complete": True, "reasons": []}\n    assert delivery["completion"]["policy"]["deliveryMode"] == "operator_review"\n'''
new = '''    detail = api.get(f"/api/v1/missions/{body['id']}", headers=auth(ALICE_TOKEN)).json()\n    assert detail["state"] == "completed"\n    async with api.factory() as session:\n        events = await store.list_mission_events_page(\n            session, body["id"], after=None, limit=100, include_attempt_events=True\n        )\n        completed = [event for event in events if event.event_type == "mission.attempt_completed"][-1]\n        payload = json.loads(completed.payload_json)\n    assert payload["completion_evidence"]["validated"] is True\n    assert payload["completion_evidence"]["delivered"] is True\n    assert payload["completion_gate"] == {"complete": True, "reasons": []}\n'''
if old not in s:
    raise SystemExit("test_issue_resolution.py: completion endpoint assertion anchor missing")
s = s.replace(old, new, 1)
p.write_text(s)

# D) Cover the new legal restart transition explicitly.
p = Path("tests/unit/test_mission_types.py")
s = p.read_text()
needle = '''            ("lost", "queued"),\n'''
replacement = '''            ("lost", "queued"),\n            ("reviewing", "queued"),\n            ("reviewing", "waiting_executor"),\n'''
if replacement not in s:
    if needle not in s:
        raise SystemExit("test_mission_types.py: transition parameter anchor missing")
    s = s.replace(needle, replacement, 1)
p.write_text(s)
PY

echo "== focused regression tests =="
pytest -q \
  tests/unit/test_mission_completion.py \
  tests/unit/test_mission_types.py \
  tests/integration/test_issue_resolution.py \
  tests/integration/test_missions.py \
  tests/integration/test_push_preauthorization.py

echo "== refresh codemap =="
governancekit --root . map

echo "== contract/docs tests =="
pytest -q tests/contract/test_docs_match_the_runtime.py tests/contract/test_openapi_document.py

echo "== full suite =="
pytest -q

echo "== stage only issue #51 product/test/docs changes =="
git add \
  gateway/app/services/mission_completion.py \
  gateway/app/services/mission_types.py \
  gateway/app/services/store.py \
  gateway/app/api/routes/missions.py \
  tests/unit/test_mission_completion.py \
  tests/unit/test_mission_types.py \
  tests/integration/test_issue_resolution.py \
  docs/codemap.md \
  "$RESULT"

git diff --cached --check
git commit -m "feat(missions): enforce completion evidence gate for #51"
git push origin development

echo "head_after=$(git rev-parse HEAD)"
echo "RESULT=$RESULT"
echo "ISSUE51=READY_FOR_REVIEW"
