"""Shared governance (policy check) and failure events."""
import logging

import httpx
from conductor.client.http.models import Task
from conductor.client.worker.worker_task import worker_task

from workers.contract import result
from workers.settings import RISK_ORDER, load_merger

log = logging.getLogger(__name__)


@worker_task(task_definition_name="shared_policy_check")
def policy_check(task: Task) -> dict:
    inp = task.input_data
    cfg = load_merger(inp["correlationId"])["governance"]
    plan = inp["plan"]
    findings, blocked = [], False

    for w in plan["waves"]:
        high = [i["componentId"] for i in w["items"] if i["risk"] == "HIGH"]
        if len(high) > cfg.get("maxHighRiskPerWave", 99):
            blocked = True
            findings.append(f"Wave {w['id']} has {len(high)} high-risk components, limit is {cfg['maxHighRiskPerWave']}")
        for i in w["items"]:
            if i["action"] in cfg.get("blockedDecisions", []):
                blocked = True
                findings.append(f"{i['componentId']}: {i['action']} is not allowed by policy")

    needs_sign_off = RISK_ORDER.index(plan["risk"]) >= RISK_ORDER.index(cfg.get("signOffAtOrAbove", "HIGH"))
    if needs_sign_off:
        findings.append(f"Plan risk is {plan['risk']}, sign-off needed at {cfg['signOffAtOrAbove']} or above")
    verdict = "BLOCKED" if blocked else "NEEDS_SIGN_OFF" if needs_sign_off else "PASS"
    return {"verdict": verdict, "findings": findings or ["No policy issues found"], "risk": plan["risk"]}


@worker_task(task_definition_name="shared_publish_failure")
def publish_failure(task: Task) -> dict:
    inp = task.input_data
    failed = inp.get("failedWorkflow") or {}
    cid = inp.get("correlationId") or failed.get("correlationId") or "unknown"
    event = {
        "eventType": "WORKFLOW_FAILED",
        "correlationId": cid,
        "workflowId": inp.get("workflowId"),
        "workflowName": failed.get("workflowName") or failed.get("workflowType"),
        "reason": inp.get("reason"),
        "failedTaskId": inp.get("failureTaskId"),
    }
    log.warning("Merger workflow failed: %s", event)
    delivered = False
    try:
        url = load_merger(cid).get("notifications", {}).get("webhookUrl")
        if url:
            httpx.post(url, json=event, timeout=10).raise_for_status()
            delivered = True
    except FileNotFoundError:
        pass
    return result(cid, "EVENT_PUBLISHED", "HIGH", [f"{event['workflowName']} failed: {event['reason']}"],
                  "INVESTIGATE", workflowId=event["workflowId"], delivered=delivered)
