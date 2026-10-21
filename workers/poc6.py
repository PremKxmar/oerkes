"""POC 6: compare records between the two banks after a wave."""
from conductor.client.http.models import Task
from conductor.client.worker.worker_task import worker_task

from workers.banks import bank
from workers.contract import result


@worker_task(task_definition_name="poc6_compare_entity")
def compare_entity(task: Task) -> dict:
    inp = task.input_data
    cid, entity = inp["correlationId"], inp["entity"]
    source = bank(cid, inp["sourceBank"]).record_hashes(entity)
    target = bank(cid, inp["targetBank"]).record_hashes(entity)
    missing = sorted(set(source) - set(target))
    mismatched = sorted(i for i in set(source) & set(target) if source[i] != target[i])
    repair_ids = missing + mismatched
    evidence = [f"{entity}: {len(source)} in {inp['sourceBank']}, {len(target)} in {inp['targetBank']}"]
    if missing:
        evidence.append(f"{len(missing)} {entity} missing in {inp['targetBank']}")
    if mismatched:
        evidence.append(f"{len(mismatched)} {entity} differ between banks")
    if not repair_ids:
        return result(cid, "MATCHED", "LOW", evidence)
    return result(cid, "MISMATCH", "MEDIUM", evidence, "REPLAY_RECORDS", entity=entity, ids=repair_ids)


@worker_task(task_definition_name="poc6_summarise")
def summarise(task: Task) -> dict:
    inp = task.input_data
    batches = [b for b in (inp.get("batches") or {}).values() if b and b.get("status")]
    evidence = [e for b in batches for e in b["evidence"]]
    repairs = [{"entity": b["recommendedAction"]["entity"], "ids": b["recommendedAction"]["ids"]}
               for b in batches if b["status"] == "MISMATCH"]
    if len(batches) < inp.get("expected", 0):
        evidence.append(f"Only {len(batches)} of {inp['expected']} entity checks returned a result")
        return result(inp["correlationId"], "INCOMPLETE", "HIGH", evidence, "MANUAL_REVIEW")
    if repairs:
        return result(inp["correlationId"], "NEEDS_REPAIR", "MEDIUM", evidence, "REPLAY_RECORDS", repairs=repairs)
    return result(inp["correlationId"], "RECONCILED", "LOW", evidence)
