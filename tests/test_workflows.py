"""Static checks on the generated workflow JSON, so a typo is caught before
it reaches Orkes."""
import json

import jsonschema
import pytest

from workers import contract
from workers.main import MODULES
from workflows import build

WORKFLOWS = {wf["name"]: wf for wf in (b() for b in build.WORKFLOWS)}
TASK_DEFS = {d["name"] for d in build.task_defs()}


def all_tasks(tasks):
    for t in tasks:
        yield t
        for case in t.get("decisionCases", {}).values():
            yield from all_tasks(case)
        yield from all_tasks(t.get("defaultCase", []))
        yield from all_tasks(t.get("loopOver", []))


def test_twelve_workflows():
    assert len(WORKFLOWS) == 12


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_refs_are_unique_and_tasks_exist(name):
    tasks = list(all_tasks(WORKFLOWS[name]["tasks"]))
    refs = [t["taskReferenceName"] for t in tasks]
    assert len(refs) == len(set(refs)), f"duplicate refs in {name}"
    for t in tasks:
        if t["type"] == "SIMPLE":
            assert t["name"] in TASK_DEFS, f"{t['name']} has no task definition"
        if t["type"] == "SUB_WORKFLOW":
            assert t["subWorkflowParam"]["name"] in WORKFLOWS


def test_every_task_def_has_a_worker():
    import importlib

    from conductor.client.automator.task_handler import _decorated_functions

    for m in MODULES:
        importlib.import_module(m)
    registered = {name for name, _ in _decorated_functions}
    assert TASK_DEFS <= registered, TASK_DEFS - registered


def test_contract_helper_matches_schema():
    schema = json.load(open(build.OUT.parent.parent / "contract" / "response.schema.json"))
    jsonschema.validate(contract.result("mrg-042", "HEALED", "LOW", ["ok"], "NONE"), schema)


def test_generated_json_is_up_to_date():
    for name, wf in WORKFLOWS.items():
        on_disk = json.loads((build.OUT / f"{name}.json").read_text())
        assert on_disk == wf, f"{name}.json is stale; run python -m workflows.build"
