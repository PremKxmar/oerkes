"""Mock Bank A and Bank B APIs used by the workers.

Run:  uvicorn mock_banks.server:app --port 8099

Scenarios (POST /admin/reset {"scenario": ...}):
  happy     every migration works first time
  demo      wave 2 has three problems for POC 5 and POC 6 to fix:
              - bill-pay returns 401 until its token is refreshed
              - customer DB rejects DD/MM/YYYY dates until a mapping is added
              - core ledger copy drops 12 transactions the first time
  rollback  same as demo, but the bill-pay token refresh fails, so the
            wave cannot be healed and has to be rolled back
"""
import copy
import hashlib
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mock_banks.data import BANK_A_INVENTORY, BANK_B_INVENTORY, bank_b_records

LEDGER_ENTITIES = ["accounts", "balances", "transactions"]
DROPPED_TRANSACTIONS = 12

app = FastAPI(title="Mock banks for the Orkes merger POC")
state = {}


def reset(scenario="demo"):
    state.clear()
    state.update({
        "scenario": scenario,
        "inventory": {"bank_a": copy.deepcopy(BANK_A_INVENTORY), "bank_b": copy.deepcopy(BANK_B_INVENTORY)},
        "records": {"bank_b": bank_b_records(), "bank_a": {e: {} for e in LEDGER_ENTITIES + ["customers"]}},
        "migrated": {},          # component id -> {"wave": n, "target": ..., "action": ...}
        "tokenFresh": scenario == "happy",
        "mappings": {},          # component id -> {field: {...}}
        "ledgerCopies": 0,
        "calls": [],
    })


reset()


def bank_or_404(bank):
    if bank not in state["inventory"]:
        raise HTTPException(404, f"unknown bank {bank}")
    return bank


def component_or_404(bank, cid):
    for c in state["inventory"][bank_or_404(bank)]:
        if c["id"] == cid:
            return c
    raise HTTPException(404, f"unknown component {cid} in {bank}")


def record_hash(record):
    return hashlib.sha1(json.dumps(record, sort_keys=True).encode()).hexdigest()[:12]


class ResetRequest(BaseModel):
    scenario: str = "demo"


class MigrateRequest(BaseModel):
    targetBank: str
    targetComponent: str | None = None
    action: str = "MIGRATE"
    wave: int | None = None


class MappingRequest(BaseModel):
    field: str
    fromFormat: str
    toFormat: str


class ReplayRequest(BaseModel):
    fromBank: str
    ids: list[str]


@app.get("/health")
def health():
    return {"ok": True, "scenario": state["scenario"]}


@app.post("/admin/reset")
def admin_reset(req: ResetRequest):
    if req.scenario not in ("happy", "demo", "rollback"):
        raise HTTPException(400, "scenario must be happy, demo or rollback")
    reset(req.scenario)
    return {"ok": True, "scenario": req.scenario}


@app.get("/admin/state")
def admin_state():
    return {
        "scenario": state["scenario"],
        "migrated": state["migrated"],
        "tokenFresh": state["tokenFresh"],
        "mappings": state["mappings"],
        "counts": {bank: {e: len(r) for e, r in recs.items()} for bank, recs in state["records"].items()},
        "calls": state["calls"][-50:],
    }


@app.get("/{bank}/inventory")
def inventory(bank: str):
    return {"bank": bank, "components": state["inventory"][bank_or_404(bank)]}


@app.get("/{bank}/components/{cid}")
def component(bank: str, cid: str):
    c = component_or_404(bank, cid)
    return {**c, "migrated": state["migrated"].get(cid)}


@app.post("/{bank}/components/{cid}/migrate")
def migrate(bank: str, cid: str, req: MigrateRequest):
    c = component_or_404(bank, cid)
    bank_or_404(req.targetBank)
    state["calls"].append({"call": "migrate", "component": cid, "action": req.action})
    failing = state["scenario"] in ("demo", "rollback")

    if cid == "b_billpay" and failing and not state["tokenFresh"]:
        return JSONResponse(status_code=401, content={"error": "token_expired", "message": "Bill-pay partner rejected the service token"})

    if cid == "b_customer_db":
        if failing and "date_of_birth" not in state["mappings"].get(cid, {}):
            return JSONResponse(status_code=422, content={
                "error": "field_format", "field": "date_of_birth",
                "message": "date_of_birth '14/03/1987' does not match target format YYYY-MM-DD",
            })
        target = state["records"][req.targetBank]["customers"]
        for rid, rec in state["records"][bank]["customers"].items():
            d, m, y = rec["date_of_birth"].split("/")
            target[rid] = {**rec, "date_of_birth": f"{y}-{m}-{d}"}

    if cid == "b_core_ledger_db":
        state["ledgerCopies"] += 1
        drop = set()
        if failing and state["ledgerCopies"] == 1:
            drop = set(sorted(state["records"][bank]["transactions"])[100:100 + DROPPED_TRANSACTIONS])
        for entity in LEDGER_ENTITIES:
            target = state["records"][req.targetBank][entity]
            for rid, rec in state["records"][bank][entity].items():
                if rid not in drop:
                    target[rid] = copy.deepcopy(rec)

    state["migrated"][cid] = {"wave": req.wave, "target": req.targetComponent, "action": req.action}
    return {"migrated": True, "component": cid, "type": c["type"], "action": req.action, "target": req.targetComponent}


@app.post("/{bank}/components/{cid}/token/refresh")
def refresh_token(bank: str, cid: str):
    component_or_404(bank, cid)
    state["calls"].append({"call": "token_refresh", "component": cid})
    if state["scenario"] == "rollback":
        return JSONResponse(status_code=500, content={"error": "partner_unavailable", "message": "Token service did not respond"})
    state["tokenFresh"] = True
    return {"refreshed": True}


@app.post("/{bank}/components/{cid}/mappings")
def add_mapping(bank: str, cid: str, req: MappingRequest):
    component_or_404(bank, cid)
    state["calls"].append({"call": "mapping", "component": cid, "field": req.field})
    state["mappings"].setdefault(cid, {})[req.field] = req.model_dump()
    return {"added": True, "mapping": req.model_dump()}


@app.post("/{bank}/components/{cid}/rollback")
def rollback(bank: str, cid: str):
    component_or_404(bank, cid)
    state["calls"].append({"call": "rollback", "component": cid})
    info = state["migrated"].pop(cid, None)
    if cid == "b_core_ledger_db" and info:
        for entity in LEDGER_ENTITIES:
            state["records"]["bank_a"][entity].clear()
    if cid == "b_customer_db" and info:
        state["records"]["bank_a"]["customers"].clear()
    return {"rolledBack": info is not None, "component": cid}


@app.get("/{bank}/records/{entity}")
def records(bank: str, entity: str):
    recs = state["records"][bank_or_404(bank)].get(entity)
    if recs is None:
        raise HTTPException(404, f"unknown entity {entity}")
    return {"bank": bank, "entity": entity, "count": len(recs), "hashes": {rid: record_hash(r) for rid, r in recs.items()}}


@app.post("/{bank}/records/{entity}/replay")
def replay(bank: str, entity: str, req: ReplayRequest):
    target = state["records"][bank_or_404(bank)].get(entity)
    source = state["records"][bank_or_404(req.fromBank)].get(entity)
    if target is None or source is None:
        raise HTTPException(404, f"unknown entity {entity}")
    state["calls"].append({"call": "replay", "entity": entity, "count": len(req.ids)})
    copied = [rid for rid in req.ids if rid in source]
    for rid in copied:
        target[rid] = copy.deepcopy(source[rid])
    return {"replayed": len(copied), "notFound": sorted(set(req.ids) - set(copied))}
