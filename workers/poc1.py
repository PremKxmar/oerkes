"""POC 1: the hub's own steps (closing a wave, rolling one back, and the
cutover report at the end)."""
from conductor.client.http.models import Task
from conductor.client.worker.worker_task import worker_task

from workers.banks import CallFailed, bank
from workers.contract import result
from workers.settings import max_risk


def outputs(join_output):
    return [v for v in (join_output or {}).values() if isinstance(v, dict) and v.get("status")]


@worker_task(task_definition_name="poc1_close_wave")
def close_wave(task: Task) -> dict:
    inp = task.input_data
    wave = inp["wave"]
    in_wave = {i["componentId"] for i in wave["items"]}
    migrations = outputs(inp.get("migrations"))
    # Inside a DO_WHILE, a task that was skipped this round still resolves to
    # its output from an earlier wave, so only keep what belongs to this one.
    heals = [h for h in outputs(inp.get("heals")) if h["recommendedAction"].get("componentId") in in_wave]
    verification = (inp.get("verification") or {}) if wave.get("reconcile") else {}
    record = {
        "waveId": wave["id"],
        "name": wave["name"],
        "components": len(wave["items"]),
        "migratedFirstTime": sum(1 for m in migrations if m["status"] == "MIGRATED"),
        "healed": [{"componentId": h["recommendedAction"].get("componentId"), "fix": h["recommendedAction"].get("fix"),
                    "how": "; ".join(h["evidence"][-2:])} for h in heals],
        "reconciliation": verification.get("status", "NOT_NEEDED"),
        "reconciliationEvidence": verification.get("evidence", []),
    }
    evidence = [f"Wave {wave['id']} ({wave['name']}) closed: {record['components']} components, "
                f"{record['migratedFirstTime']} first time, {len(heals)} healed by POC 5"]
    if verification:
        evidence.append(f"Reconciliation: {record['reconciliation']}")
    return {**result(inp["correlationId"], "WAVE_DONE", wave["risk"], evidence), "record": record}


@worker_task(task_definition_name="poc1_rollback_wave")
def rollback_wave(task: Task) -> dict:
    inp = task.input_data
    cid, wave = inp["correlationId"], inp["wave"]
    source = bank(cid, inp["sourceBank"])
    rolled, errors = [], []
    for item in reversed(wave["items"]):
        try:
            if source.rollback(item["componentId"])["rolledBack"]:
                rolled.append(item["componentId"])
        except CallFailed as e:
            errors.append(f"{item['componentId']}: {e.message}")
    evidence = [f"Rolled back {len(rolled)} components of wave {wave['id']}: {', '.join(rolled) or 'none were migrated'}"]
    evidence += [f"Rollback error {e}" for e in errors]
    status = "ROLLED_BACK" if not errors else "ROLLBACK_INCOMPLETE"
    return result(cid, status, "HIGH", evidence, "MANUAL_REVIEW" if errors else "NONE", reason=inp.get("reason"))


@worker_task(task_definition_name="poc1_summarise_execution")
def summarise_execution(task: Task) -> dict:
    inp = task.input_data
    records = []
    for key, iteration in sorted((inp.get("loop") or {}).items()):
        if not isinstance(iteration, dict):
            continue
        for ref, out in iteration.items():
            if ref.startswith("close_wave") and isinstance(out, dict) and out.get("record"):
                records.append(out["record"])
    records.sort(key=lambda r: r["waveId"])
    evidence = [f"Wave {r['waveId']} ({r['name']}): {r['components']} components, {len(r['healed'])} healed, "
                f"reconciliation {r['reconciliation']}" for r in records]
    return {**result(inp["correlationId"], "PLAN_EXECUTED", max_risk(*inp.get("risks", [])), evidence), "waves": records}


@worker_task(task_definition_name="poc1_cutover_report")
def cutover_report(task: Task) -> dict:
    """The closing summary for the merger team: what moved, what broke and
    how it was fixed, and what someone still has to do."""
    inp = task.input_data
    cid = inp["correlationId"]
    plan = inp.get("plan") or {}
    execution = inp.get("execution") or {}
    waves_done = execution.get("waves") or []
    planned = plan.get("waves", [])
    items = [i for w in planned for i in w["items"]]
    complete = execution.get("status") == "PLAN_EXECUTED" and len(waves_done) == len(planned)

    evidence = [f"All {len(planned)} waves completed, {len(items)} Bank B components in scope" if complete
                else f"Stopped before all {len(planned)} waves were done; waves already closed stay migrated"]
    evidence += execution.get("evidence", [])
    if not complete:
        evidence.append(f"Execution stopped: {inp.get('executionError') or execution.get('status') or 'no result'}")

    follow_up = []
    for i in items:
        if i["action"] == "REHOST":
            follow_up.append(f"{i['componentId']} was rehosted as is; decide whether to rebuild it on Bank A's stack")
        if i["action"] == "KEEP":
            follow_up.append(f"{i['componentId']} was kept on Bank B; set a date to revisit")
    migrated = [i["componentId"] for i in items if i["action"] == "MIGRATE"]
    if migrated and complete:
        follow_up.append(f"Decommission {len(migrated)} Bank B components after the parallel run: {', '.join(migrated)}")
    for w in waves_done:
        for h in w["healed"]:
            follow_up.append(f"{h['componentId']} needed {h['fix']} during wave {w['waveId']}; "
                             "fix the root cause before the next merger")
        if w["reconciliation"] not in ("VERIFIED", "NOT_NEEDED"):
            follow_up.append(f"Wave {w['waveId']} reconciliation ended as {w['reconciliation']}; check the audit trail")

    status = "CUTOVER_COMPLETE" if complete else "CUTOVER_INCOMPLETE"
    return {**result(cid, status, plan.get("risk", "HIGH") if not complete else "LOW", evidence, "FOLLOW_UP",
                     actions=follow_up), "waves": waves_done}
