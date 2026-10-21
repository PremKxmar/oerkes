"""POC 5: diagnose a failure, apply the runbook fix, and check it worked."""
from conductor.client.http.models import Task
from conductor.client.worker.worker_task import worker_task

from workers.banks import CallFailed, bank
from workers.settings import load_merger


@worker_task(task_definition_name="poc5_diagnose")
def diagnose(task: Task) -> dict:
    inp = task.input_data
    incident = inp["incident"]
    heal_cfg = load_merger(inp["correlationId"])["selfHeal"]
    runbook = heal_cfg["runbooks"].get(incident.get("errorCode"))
    if not runbook:
        return {"action": "ESCALATE", "needsApproval": True, "risk": "HIGH", "known": False, "params": {},
                "reason": f"No runbook for {incident.get('errorCode')}: {incident.get('message')}"}

    params = {}
    if runbook["action"] == "APPLY_MAPPING":
        field = (incident.get("details") or {}).get("field")
        mapping = heal_cfg.get("mappings", {}).get(field)
        if not mapping:
            return {"action": "ESCALATE", "needsApproval": True, "risk": "HIGH", "known": False, "params": {},
                    "reason": f"Field {field} has no known mapping in the merger YAML"}
        params = {"field": field, **mapping}
    if runbook["action"] == "REPLAY_RECORDS":
        params = {"repairs": (incident.get("details") or {}).get("repairs", [])}
    return {"action": runbook["action"], "needsApproval": runbook["needsApproval"], "risk": runbook["risk"],
            "known": True, "params": params, "reason": f"{incident['errorCode']} on {incident['componentId']}"}


@worker_task(task_definition_name="poc5_apply_fix")
def apply_fix(task: Task) -> dict:
    inp = task.input_data
    cid, incident, fix = inp["correlationId"], inp["incident"], inp["fix"]
    source = bank(cid, incident["sourceBank"])
    target = bank(cid, incident["targetBank"])
    try:
        if fix["action"] == "REFRESH_TOKEN":
            source.refresh_token(incident["componentId"])
            message = f"Refreshed the service token for {incident['componentId']}"
        elif fix["action"] == "APPLY_MAPPING":
            p = fix["params"]
            source.add_mapping(incident["componentId"], p["field"], p["fromFormat"], p["toFormat"])
            message = f"Added mapping {p['field']}: {p['fromFormat']} -> {p['toFormat']}"
        elif fix["action"] == "REPLAY_RECORDS":
            counts = []
            for r in fix["params"]["repairs"]:
                out = target.replay(r["entity"], incident["sourceBank"], r["ids"])
                counts.append(f"{out['replayed']} {r['entity']}")
            message = "Replayed " + ", ".join(counts)
        else:
            message = "No change needed before retrying"
    except CallFailed as e:
        return {"applied": False, "message": f"Fix {fix['action']} failed: {e.message}"}
    return {"applied": True, "message": message}


@worker_task(task_definition_name="poc5_verify_fix")
def verify_fix(task: Task) -> dict:
    inp = task.input_data
    cid, incident, fix = inp["correlationId"], inp["incident"], inp["fix"]
    if fix["action"] == "REPLAY_RECORDS":
        target = bank(cid, incident["targetBank"])
        still_missing = []
        for r in fix["params"]["repairs"]:
            present = target.record_hashes(r["entity"])
            still_missing += [i for i in r["ids"] if i not in present]
        if still_missing:
            return {"healed": False, "message": f"{len(still_missing)} records still missing"}
        return {"healed": True, "message": "All replayed records are present in the target"}

    item = incident["item"]
    try:
        bank(cid, incident["sourceBank"]).migrate(item["componentId"], incident["targetBank"],
                                                  item.get("targetComponent"), item["action"], incident.get("wave"))
    except CallFailed as e:
        return {"healed": False, "message": f"Retry still fails: {e.error_code} {e.message}"}
    return {"healed": True, "message": f"{item['componentId']} migrated on retry"}
