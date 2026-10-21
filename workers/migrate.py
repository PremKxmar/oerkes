"""Migration steps used by the migrate_component workflow, one per kind of
component. A bank error comes back as data (ok: false + errorCode) so POC 5
can pick it up; a network error raises and Conductor retries the task."""
from conductor.client.http.models import Task
from conductor.client.worker.worker_task import worker_task

from workers.banks import CallFailed, bank

HOW = {
    "database": "Copied data into {target}",
    "integration": "Re-pointed the integration to {target}",
    "infrastructure": "Moved onto {target}",
    "application": "Moved users and data to {target}",
}


def run_migration(task, kind):
    inp = task.input_data
    item = inp["item"]
    source = bank(inp["correlationId"], inp["sourceBank"])
    base = {"componentId": item["componentId"], "type": item["type"], "action": item["action"]}
    try:
        source.migrate(item["componentId"], inp["targetBank"], item.get("targetComponent"), item["action"], inp.get("wave"))
    except CallFailed as e:
        return {**base, "ok": False, "errorCode": e.error_code, "message": e.message, "details": e.details}
    target = item.get("targetComponent") or f"{inp['targetBank']} hosting"
    note = HOW[kind].format(target=target) if item["action"] != "REHOST" else f"Rehosted on {target}"
    return {**base, "ok": True, "message": note}


@worker_task(task_definition_name="migrate_database")
def migrate_database(task: Task) -> dict:
    return run_migration(task, "database")


@worker_task(task_definition_name="migrate_integration")
def migrate_integration(task: Task) -> dict:
    return run_migration(task, "integration")


@worker_task(task_definition_name="migrate_infrastructure")
def migrate_infrastructure(task: Task) -> dict:
    return run_migration(task, "infrastructure")


@worker_task(task_definition_name="migrate_application")
def migrate_application(task: Task) -> dict:
    return run_migration(task, "application")
