"""POC 2: assess both stacks and turn the answers into a wave plan."""
from conductor.client.http.models import Task
from conductor.client.worker.worker_task import worker_task

from agents.compare_agent import compare
from workers.banks import bank
from workers.contract import result
from workers.settings import load_merger, max_risk


def assessment(capability, source, target, decision, risk, reason, decided_by):
    target_id = target[0]["id"] if target else None
    return {
        "capability": capability,
        "decision": decision,
        "risk": risk,
        "reason": reason,
        "decidedBy": decided_by,
        "items": [{
            "componentId": c["id"], "name": c["name"], "type": c["type"], "capability": capability,
            "action": decision, "targetComponent": target_id, "risk": risk,
        } for c in source],
    }


@worker_task(task_definition_name="poc2_fetch_inventories")
def fetch_inventories(task: Task) -> dict:
    inp = task.input_data
    cid = inp["correlationId"]
    source = bank(cid, inp["acquired"]).inventory()
    target = bank(cid, inp["acquirer"]).inventory()
    capabilities = []
    for cap in sorted({c["capability"] for c in source}):
        capabilities.append({
            "capability": cap,
            "source": [c for c in source if c["capability"] == cap],
            "target": [c for c in target if c["capability"] == cap],
        })
    return {"capabilities": capabilities, "sourceCount": len(source), "targetCount": len(target)}


@worker_task(task_definition_name="poc2_match_rule")
def match_rule(task: Task) -> dict:
    inp = task.input_data
    rule = load_merger(inp["correlationId"])["assessment"]["rules"].get(inp["capability"])
    if not rule:
        return {"matched": False}
    return {"matched": True, "assessment": assessment(
        inp["capability"], inp["source"], inp["target"], rule["decision"], rule.get("risk", "LOW"), rule["reason"], "rule")}


@worker_task(task_definition_name="poc2_compare_agent")
def compare_agent(task: Task) -> dict:
    inp = task.input_data
    answer = compare(inp["capability"], inp["source"], inp["target"])
    return {"assessment": assessment(
        inp["capability"], inp["source"], inp["target"], answer["decision"], answer["risk"], answer["reason"], answer["decidedBy"])}


@worker_task(task_definition_name="poc2_build_wave_plan")
def build_wave_plan(task: Task) -> dict:
    inp = task.input_data
    cid = inp["correlationId"]
    cfg = load_merger(cid)
    assessments = [v["recommendedAction"]["assessment"] for _, v in sorted((inp.get("assessments") or {}).items())
                   if v and v.get("recommendedAction", {}).get("assessment")]
    items = [i for a in assessments for i in a["items"]]

    wave_cfg = cfg["assessment"]["waves"]
    waves = []
    for w in wave_cfg:
        wave_items = [i for i in items if i["type"] in w["types"]]
        if wave_items:
            waves.append({"id": w["id"], "name": w["name"], "items": wave_items, "reconcile": w.get("reconcile", []),
                          "risk": max_risk(*[i["risk"] for i in wave_items])})
    known_types = {t for w in wave_cfg for t in w["types"]}
    leftover = [i for i in items if i["type"] not in known_types]
    if leftover:
        waves.append({"id": len(wave_cfg) + 1, "name": "Unplanned types", "items": leftover, "reconcile": [],
                      "risk": "HIGH"})

    plan = {"mergerId": cid, "acquirer": inp["acquirer"], "acquired": inp["acquired"], "waves": waves,
            "risk": max_risk(*[w["risk"] for w in waves])}
    by_agent = sum(1 for a in assessments if a["decidedBy"].startswith("agent"))
    evidence = [f"{len(items)} Bank B components across {len(assessments)} capabilities",
                f"{len(assessments) - by_agent} decided by config rules, {by_agent} by the compare agent"]
    evidence += [f"Wave {w['id']} ({w['name']}): {len(w['items'])} components, risk {w['risk']}" for w in waves]
    if leftover:
        evidence.append(f"{len(leftover)} components have a type no wave covers; add it to the merger YAML")
    return result(cid, "PLAN_READY", plan["risk"], evidence, "EXECUTE_PLAN", plan=plan)
