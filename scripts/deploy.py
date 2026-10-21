"""Register the task definitions and all 12 workflows.

    python -m scripts.deploy
"""
import json
from pathlib import Path

from scripts.conductor_api import Conductor
from workflows import build

DEFS = Path(build.OUT)


def main():
    build.main()
    api = Conductor()
    task_defs = json.loads((DEFS / "_taskdefs.json").read_text())
    try:
        api.register_task_defs(task_defs)
    except RuntimeError:
        # Orkes refuses to create a task def that already exists; update instead.
        for d in task_defs:
            api.update_task_def(d)
    workflows = [json.loads(p.read_text()) for p in sorted(DEFS.glob("*.json")) if not p.name.startswith("_")]
    api.put_workflows(workflows)
    print(f"Registered {len(task_defs)} task definitions and {len(workflows)} workflows on {api.base}")


if __name__ == "__main__":
    main()
