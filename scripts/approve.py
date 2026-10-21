"""List and answer pending approvals (WAIT tasks) in a run.

    python -m scripts.approve                     # list what is waiting
    python -m scripts.approve --yes --by Prem     # approve everything waiting
    python -m scripts.approve --no --task <id> --comment "not tonight"

Uses the run in .last_run unless --workflow is given.
"""
import argparse
import json

from scripts.conductor_api import Conductor
from scripts.env import ROOT


def pending(api, root_id):
    for _, wf in api.tree(root_id):
        for t in wf.get("tasks", []):
            if t.get("taskType") == "WAIT" and t.get("status") == "IN_PROGRESS":
                yield wf, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", help="root workflow id (default: .last_run)")
    ap.add_argument("--task", help="only this task id")
    answer = ap.add_mutually_exclusive_group()
    answer.add_argument("--yes", action="store_true")
    answer.add_argument("--no", action="store_true")
    ap.add_argument("--by", default="poc-team")
    ap.add_argument("--comment", default="")
    args = ap.parse_args()

    api = Conductor()
    root = args.workflow or (ROOT / ".last_run").read_text().strip()
    waiting = [(wf, t) for wf, t in pending(api, root) if not args.task or t["taskId"] == args.task]
    if not waiting:
        print("Nothing is waiting for approval.")
        return
    for wf, t in waiting:
        title = t["inputData"].get("approvalTitle", t["referenceTaskName"])
        print(f"- {title}\n  workflow {wf['workflowName']} ({wf['workflowId']}), task {t['taskId']}")
        print("  details:", json.dumps(t["inputData"].get("details"))[:400])
        if args.yes or args.no:
            api.complete_task(wf["workflowId"], t["taskId"],
                              {"approved": bool(args.yes), "by": args.by, "comment": args.comment})
            print("  ->", "approved" if args.yes else "rejected")


if __name__ == "__main__":
    main()
