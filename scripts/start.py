"""Start the hub, or any one workflow on its own.

    python -m scripts.start                         # full merger, mrg-042
    python -m scripts.start --auto --scenario demo  # no approvals, reset mock banks first
    python -m scripts.start poc6_reconcile --payload '{"entities": ["accounts"], "sourceBank": "bank_b", "targetBank": "bank_a"}'

The workflow ID is saved to .last_run so approve.py and show.py can find it.
"""
import argparse
import json

import httpx

from scripts.conductor_api import Conductor
from scripts.env import ROOT
from workers.settings import load_merger

EVENT_TYPES = {
    "poc1_merger_orchestrator": "MERGER_START", "poc1_execute_plan": "WAVE_PLAN_EXECUTE",
    "poc2_stack_assessment": "STACK_ASSESSMENT_REQUEST", "poc2_assess_capability": "CAPABILITY_ASSESSMENT",
    "shared_governance": "GOVERNANCE_REVIEW", "verify_and_repair": "VERIFY_WAVE", "poc5_self_heal": "INCIDENT",
    "poc6_reconcile": "RECON_REQUEST", "poc6_compare_batch": "RECON_BATCH", "migrate_component": "COMPONENT_MIGRATE",
    "rollback_wave": "ROLLBACK_REQUEST",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow", nargs="?", default="poc1_merger_orchestrator")
    ap.add_argument("--merger", default="mrg-042", help="correlationId = config/mergers/<id>.yaml")
    ap.add_argument("--payload", help="JSON payload; defaults to acquirer/acquired from the merger YAML")
    ap.add_argument("--auto", action="store_true", help="skip approvals (escalations still go to a person)")
    ap.add_argument("--scenario", choices=["happy", "demo", "rollback"], help="reset the mock banks first")
    ap.add_argument("--mock-url", default="http://localhost:8099")
    args = ap.parse_args()

    cfg = load_merger(args.merger)
    if args.scenario:
        httpx.post(f"{args.mock_url}/admin/reset", json={"scenario": args.scenario}, timeout=10).raise_for_status()

    context = {"mergerId": cfg["mergerId"], **cfg.get("run", {})}
    if args.auto:
        context["autoApprove"] = True
    payload = json.loads(args.payload) if args.payload else {"acquirer": cfg["acquirer"], "acquired": cfg["acquired"]}
    body = {"eventType": EVENT_TYPES.get(args.workflow, "MANUAL"), "correlationId": args.merger,
            "context": context, "payload": payload}

    workflow_id = Conductor().start(args.workflow, body, args.merger)
    (ROOT / ".last_run").write_text(workflow_id)
    print(f"Started {args.workflow}: {workflow_id}")


if __name__ == "__main__":
    main()
