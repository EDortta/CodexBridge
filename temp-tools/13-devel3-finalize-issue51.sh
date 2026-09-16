#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ "$(git branch --show-current)" != "development" ]]; then
  echo "ERROR: run this from branch development" >&2
  exit 2
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: tracked working tree is not clean; refusing to overwrite local work" >&2
  git status --short
  exit 2
fi

mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-devel3-issue51-finalize.txt"
exec > >(tee "$RESULT") 2>&1

echo "== issue #51 finalization =="
echo "head_before=$(git rev-parse HEAD)"

python3 - <<'PY'
from pathlib import Path

# 1) Completion policy helpers and operator-review semantics.
p = Path("gateway/app/services/mission_completion.py")
s = p.read_text()
old = '''    elif mode == DeliveryMode.OPERATOR_REVIEW:\n        if evidence.review_outcome not in {"approved", "accepted"}:\n            reasons.append("operator_review_missing")\n'''
new = '''    elif mode == DeliveryMode.OPERATOR_REVIEW:\n        # Operator-review-only is a delivery mode, not an approval decision.\n        # Reaching this mode means the implementation/validation evidence is\n        # handed back to the operator; explicit approval is required only when\n        # policy.require_review says so.\n        if not evidence.implemented:\n            reasons.append("operator_review_handoff_missing")\n'''
if old not in s:
    raise SystemExit("mission_completion.py: operator-review anchor not found")
s = s.replace(old, new, 1)
anchor = '''@dataclass(frozen=True)\nclass CompletionDecision:\n'''
helpers = '''def infer_delivery_mode(delivery_json: str | None) -> DeliveryMode:\n    """Infer the safe delivery mode from the Mission's durable request.\n\n    No delivery request means "return the validated work to the operator".\n    A requested delivery is commit-only unless it explicitly authorizes push.\n    PR/artifact modes are never inferred because they require explicit project\n    policy and external evidence.\n    """\n    raw = _json_dict(delivery_json)\n    if not raw:\n        return DeliveryMode.OPERATOR_REVIEW\n    if bool(raw.get("allow_push")):\n        return DeliveryMode.PUSH_BRANCH\n    return DeliveryMode.COMMIT_ONLY\n\n\ndef completion_policy_from_project_config(\n    config_json: str | None, delivery_json: str | None\n) -> CompletionPolicy:\n    """Build issue #51's gate from durable project configuration.\n\n    Projects may define ``completion_policy`` in their existing config JSON:\n    ``required_validation_kinds``, ``delivery_mode``, ``require_review`` and\n    ``allow_merge``. Missing or malformed values fail to conservative defaults:\n    tests are required, merge is forbidden, and delivery mode is inferred only\n    from the Mission's already-authorized delivery request.\n    """\n    config = _json_dict(config_json)\n    raw = config.get("completion_policy")\n    raw = raw if isinstance(raw, dict) else {}\n\n    kinds = raw.get("required_validation_kinds", ["test"])\n    if not isinstance(kinds, list) or not all(isinstance(item, str) and item for item in kinds):\n        kinds = ["test"]\n\n    inferred = infer_delivery_mode(delivery_json)\n    try:\n        mode = DeliveryMode(raw.get("delivery_mode", inferred.value))\n    except (TypeError, ValueError):\n        mode = inferred\n\n    return CompletionPolicy(\n        required_validation_kinds=tuple(kinds),\n        delivery_mode=mode,\n        require_review=bool(raw.get("require_review", False)),\n        allow_merge=bool(raw.get("allow_merge", False)),\n    )\n\n\n'''
if anchor not in s:
    raise SystemExit("mission_completion.py: CompletionDecision anchor not found")
s = s.replace(anchor, helpers + anchor, 1)
p.write_text(s)

# 2) Gate the durable Mission transition inside store_result.
p = Path("gateway/app/services/store.py")
s = p.read_text()
import_anchor = '''from gateway.app.services.mission_types import (\n    MissionState,\n'''
import_block = '''from gateway.app.services.mission_completion import (\n    build_completion_evidence,\n    completion_policy_from_project_config,\n    evaluate_completion_gate,\n)\n'''
if import_block not in s:
    if import_anchor not in s:
        raise SystemExit("store.py: mission_types import anchor not found")
    s = s.replace(import_anchor, import_block + import_anchor, 1)
old = '''            await transition_mission_state(\n                session,\n                mission,\n                mission_state_from_task_state(task.state),\n                task_id=task.id,\n                event_type="mission.attempt_completed",\n                payload={"task_state": task.state},\n            )\n'''
new = '''            mission_target = mission_state_from_task_state(task.state)\n            completion_payload: dict = {"task_state": task.state}\n            if task.state == TaskState.COMPLETED.value and mission.requested_mode == TaskMode.IMPLEMENT.value:\n                project = await session.get(ProjectModel, mission.project_id)\n                policy = completion_policy_from_project_config(\n                    project.config_json if project is not None else None,\n                    mission.delivery_json,\n                )\n                evidence = build_completion_evidence(\n                    task_state=task.state,\n                    result_json=task.result_json,\n                    delivery_result_json=task.delivery_result_json,\n                    delivery_mode=policy.delivery_mode.value,\n                )\n                decision = evaluate_completion_gate(evidence, policy)\n                completion_payload["completion_evidence"] = evidence.to_dict()\n                completion_payload["completion_gate"] = decision.to_dict()\n                if not decision.complete:\n                    # The execution attempt finished, but the Mission did not.\n                    # REVIEWING is deliberately non-terminal and keeps the\n                    # missing validation/delivery evidence visible to operators.\n                    mission_target = MissionState.REVIEWING.value\n                    mission.last_error = "Completion gate: " + ", ".join(decision.reasons)\n                else:\n                    mission.last_error = None\n            await transition_mission_state(\n                session,\n                mission,\n                mission_target,\n                task_id=task.id,\n                event_type="mission.attempt_completed",\n                payload=completion_payload,\n            )\n'''
if old not in s:
    raise SystemExit("store.py: store_result transition anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)

# 3) Expose consolidated completion evidence through the existing delivery endpoint.
p = Path("gateway/app/api/routes/missions.py")
s = p.read_text()
import_anchor = '''from gateway.app.services.issue_resolution import resolve_issue_as_mission\n'''
import_block = '''from gateway.app.services.mission_completion import (\n    build_completion_evidence,\n    completion_policy_from_project_config,\n    evaluate_completion_gate,\n)\n'''
if import_block not in s:
    if import_anchor not in s:
        raise SystemExit("missions.py: issue_resolution import anchor not found")
    s = s.replace(import_anchor, import_anchor + import_block, 1)
helper_anchor = '''@router.get("/missions/{mission_id}/delivery", tags=["missions"])\n'''
helper = '''def _completion_contract_dto(\n    mission: MissionModel, task: TaskModel | None, project_config_json: str | None\n) -> dict:\n    policy = completion_policy_from_project_config(project_config_json, mission.delivery_json)\n    if task is None:\n        evidence = build_completion_evidence(\n            task_state=mission.state,\n            result_json=None,\n            delivery_result_json=None,\n            delivery_mode=policy.delivery_mode.value,\n        )\n    else:\n        evidence = build_completion_evidence(\n            task_state=task.state,\n            result_json=task.result_json,\n            delivery_result_json=task.delivery_result_json,\n            delivery_mode=policy.delivery_mode.value,\n        )\n    gate = evaluate_completion_gate(evidence, policy)\n    return {\n        "evidence": evidence.to_dict(),\n        "gate": gate.to_dict(),\n        "policy": {\n            "requiredValidationKinds": list(policy.required_validation_kinds),\n            "deliveryMode": policy.delivery_mode.value,\n            "requireReview": policy.require_review,\n            "allowMerge": policy.allow_merge,\n        },\n    }\n\n\n'''
if helper not in s:
    if helper_anchor not in s:
        raise SystemExit("missions.py: delivery route anchor not found")
    s = s.replace(helper_anchor, helper + helper_anchor, 1)
old = '''    task = await store.get_mission_active_task(session, mission)\n    response.headers["Cache-Control"] = "no-store"\n    return _delivery_evidence_dto(mission, task)\n'''
new = '''    task = await store.get_mission_active_task(session, mission)\n    project = await session.get(ProjectModel, mission.project_id)\n    response.headers["Cache-Control"] = "no-store"\n    body = _delivery_evidence_dto(mission, task)\n    body["completion"] = _completion_contract_dto(\n        mission, task, project.config_json if project is not None else None\n    )\n    return body\n'''
if old not in s:
    raise SystemExit("missions.py: get_mission_delivery body anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)

# 4) Extend unit coverage for the policy defaults/config.
p = Path("tests/unit/test_mission_completion.py")
s = p.read_text()
s = s.replace(
    'from gateway.app.services.mission_completion import build_completion_evidence\n',
    'from gateway.app.services.mission_completion import (\n'
    '    CompletionPolicy,\n'
    '    DeliveryMode,\n'
    '    build_completion_evidence,\n'
    '    completion_policy_from_project_config,\n'
    '    evaluate_completion_gate,\n'
    ')\n',
    1,
)
extra = '''\n\ndef test_default_policy_requires_tests_and_returns_no_delivery_to_operator() -> None:\n    policy = completion_policy_from_project_config(None, None)\n    assert policy.required_validation_kinds == ("test",)\n    assert policy.delivery_mode == DeliveryMode.OPERATOR_REVIEW\n    assert policy.allow_merge is False\n\n\ndef test_operator_review_delivery_does_not_fake_operator_approval() -> None:\n    evidence = build_completion_evidence(\n        task_state="completed",\n        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),\n        delivery_result_json=None,\n        delivery_mode="operator_review",\n    )\n    decision = evaluate_completion_gate(evidence, CompletionPolicy(delivery_mode=DeliveryMode.OPERATOR_REVIEW))\n    assert decision.complete is True\n    reviewed = evaluate_completion_gate(\n        evidence,\n        CompletionPolicy(delivery_mode=DeliveryMode.OPERATOR_REVIEW, require_review=True),\n    )\n    assert reviewed.complete is False\n    assert "review_not_approved" in reviewed.reasons\n\n\ndef test_project_policy_can_require_static_checks_and_push() -> None:\n    policy = completion_policy_from_project_config(\n        json.dumps({\n            "completion_policy": {\n                "required_validation_kinds": ["test", "static"],\n                "delivery_mode": "push_branch",\n                "require_review": True,\n            }\n        }),\n        json.dumps({"allow_push": False}),\n    )\n    assert policy.required_validation_kinds == ("test", "static")\n    assert policy.delivery_mode == DeliveryMode.PUSH_BRANCH\n    assert policy.require_review is True\n'''
if 'test_default_policy_requires_tests_and_returns_no_delivery_to_operator' not in s:
    s += extra
p.write_text(s)

# 5) Add integration coverage on the real issue->Mission path.
p = Path("tests/integration/test_issue_resolution.py")
s = p.read_text()
extra = '''\n\n@pytest.mark.asyncio\nasync def test_implement_mission_waits_for_completion_gate_when_validation_is_missing(api) -> None:\n    issue_id = await _issue_id(api.factory)\n    body = _resolve(api, issue_id).json()\n    async with api.factory() as session:\n        await store.update_task_state(session, body["id"], TaskState.RUNNING)\n        await store.store_result(\n            session,\n            body["id"],\n            {"task_id": body["id"], "final_state": "completed"},\n            TaskState.COMPLETED,\n        )\n\n    detail = api.get(f"/api/v1/missions/{body['id']}", headers=auth(ALICE_TOKEN)).json()\n    assert detail["state"] == "reviewing"\n    assert "missing_validation:test" in detail["lastError"]\n\n\n@pytest.mark.asyncio\nasync def test_validated_operator_review_mission_completes_and_exposes_evidence(api) -> None:\n    issue_id = await _issue_id(api.factory)\n    body = _resolve(api, issue_id).json()\n    async with api.factory() as session:\n        await store.update_task_state(session, body["id"], TaskState.RUNNING)\n        await store.store_result(\n            session,\n            body["id"],\n            {\n                "task_id": body["id"],\n                "final_state": "completed",\n                "tests_ran": [{"name": "pytest focused", "passed": True}],\n            },\n            TaskState.COMPLETED,\n        )\n\n    detail = api.get(f"/api/v1/missions/{body['id']}", headers=auth(ALICE_TOKEN)).json()\n    assert detail["state"] == "completed"\n    delivery = api.get(\n        f"/api/v1/missions/{body['id']}/delivery", headers=auth(ALICE_TOKEN)\n    ).json()\n    assert delivery["completion"]["evidence"]["validated"] is True\n    assert delivery["completion"]["evidence"]["delivered"] is True\n    assert delivery["completion"]["gate"] == {"complete": True, "reasons": []}\n    assert delivery["completion"]["policy"]["deliveryMode"] == "operator_review"\n'''
if 'test_implement_mission_waits_for_completion_gate_when_validation_is_missing' not in s:
    s += extra
p.write_text(s)
PY

echo "== focused tests =="
pytest -q tests/unit/test_mission_completion.py tests/integration/test_issue_resolution.py

echo "== refresh codemap =="
governancekit --root . map

echo "== contract/docs tests =="
pytest -q tests/contract/test_docs_match_the_runtime.py tests/contract/test_openapi_document.py

echo "== full suite =="
pytest -q

echo "== staged implementation files =="
git add \
  gateway/app/services/mission_completion.py \
  gateway/app/services/store.py \
  gateway/app/api/routes/missions.py \
  tests/unit/test_mission_completion.py \
  tests/integration/test_issue_resolution.py \
  docs/codemap.md \
  "$RESULT"

git diff --cached --check

git commit -m "feat(missions): enforce completion evidence gate for #51"
git push origin development

echo "head_after=$(git rev-parse HEAD)"
echo "RESULT=$RESULT"
echo "ISSUE51=READY_FOR_REVIEW"
