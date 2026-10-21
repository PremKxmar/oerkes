"""Show a run as a tree, plus its output.

    python -m scripts.show            # the run in .last_run
    python -m scripts.show --wait     # poll until it finishes or needs an approval
"""
import argparse
import json
import time

from scripts.conductor_api import Conductor
from scripts.env import ROOT

DONE = {"COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"}


def print_tree(api, root):
    for depth, wf in api.tree(root):
        pad = "  " * depth
        print(f"{pad}{wf['workflowName']}: {wf['status']}  ({wf['workflowId']})")
        for t in wf.get("tasks", []):
            if t.get("taskType") == "WAIT" and t.get("status") == "IN_PROGRESS":
                print(f"{pad}  waiting for approval: {t['inputData'].get('approvalTitle')}")
            if t.get("status") in ("FAILED", "FAILED_WITH_TERMINAL_ERROR", "TIMED_OUT"):
                print(f"{pad}  {t['referenceTaskName']} {t['status']}: {t.get('reasonForIncompletion', '')[:200]}")


def waiting_for_person(api, root):
    return any(t.get("taskType") == "WAIT" and t.get("status") == "IN_PROGRESS"
               for _, wf in api.tree(root) for t in wf.get("tasks", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    api = Conductor()
    root = args.workflow or (ROOT / ".last_run").read_text().strip()

    deadline = time.time() + args.timeout
    while args.wait and time.time() < deadline:
        if api.workflow(root)["status"] in DONE or waiting_for_person(api, root):
            break
        time.sleep(2)

    print_tree(api, root)
    wf = api.workflow(root)
    if wf["status"] in DONE:
        print("\nOutput:")
        print(json.dumps(wf.get("output"), indent=2))


if __name__ == "__main__":
    main()
