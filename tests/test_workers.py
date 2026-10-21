from agents.compare_agent import compare
from tests.conftest import task
from workers import governance, migrate, poc2, poc5, poc6

BILLPAY = {"componentId": "b_billpay", "type": "api_integration", "action": "MIGRATE", "targetComponent": "a_billpay"}
LEDGER = {"componentId": "b_core_ledger_db", "type": "database", "action": "MIGRATE", "targetComponent": "a_core_ledger_db"}


def migrate_task(item):
    return task(item=item, sourceBank="bank_b", targetBank="bank_a", wave=2)


def test_agent_rehosts_when_acquirer_has_nothing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = compare("wire_transfers", [{"id": "b_wire_desk", "name": "Wire desk", "type": "application"}], [])
    assert out["decision"] == "REHOST" and out["decidedBy"] == "agent-rules"


def test_agent_flags_interface_change_as_high_risk(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = compare("ach_payments", [{"id": "b", "name": "SFTP", "type": "file_transfer"}],
                  [{"id": "a", "name": "API", "type": "api_integration"}])
    assert out == {**out, "decision": "MIGRATE", "risk": "HIGH"}


def test_plan_puts_foundation_first_and_reconciles_data_wave(mock_banks, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    caps = poc2.fetch_inventories(task(acquirer="bank_a", acquired="bank_b"))["capabilities"]
    assessments = {}
    for c in caps:
        rule = poc2.match_rule(task(capability=c["capability"], source=c["source"], target=c["target"]))
        a = rule["assessment"] if rule["matched"] else poc2.compare_agent(
            task(capability=c["capability"], source=c["source"], target=c["target"]))["assessment"]
        assessments[f"assess_{c['capability']}"] = {"status": "ASSESSED", "recommendedAction": {"assessment": a}}
    out = poc2.build_wave_plan(task(acquirer="bank_a", acquired="bank_b", assessments=assessments))

    plan = out["recommendedAction"]["plan"]
    assert out["status"] == "PLAN_READY"
    assert [w["name"] for w in plan["waves"]] == ["Foundation", "Data and integrations", "Applications"]
    assert {i["type"] for i in plan["waves"][0]["items"]} == {"infrastructure", "security", "identity"}
    assert plan["waves"][1]["reconcile"] == ["accounts", "balances", "transactions"]
    assert sum(len(w["items"]) for w in plan["waves"]) == 13


def test_billpay_401_is_healed_by_token_refresh(mock_banks):
    failed = migrate.migrate_integration(migrate_task(BILLPAY))
    assert failed["ok"] is False and failed["errorCode"] == "AUTH_EXPIRED"

    incident = {**failed, "item": BILLPAY, "sourceBank": "bank_b", "targetBank": "bank_a", "wave": 2}
    fix = poc5.diagnose(task(incident=incident))
    assert fix["action"] == "REFRESH_TOKEN" and fix["needsApproval"] is False
    assert poc5.apply_fix(task(incident=incident, fix=fix))["applied"]
    assert poc5.verify_fix(task(incident=incident, fix=fix))["healed"]


def test_field_format_fix_needs_approval(mock_banks):
    item = {"componentId": "b_customer_db", "type": "database", "action": "MIGRATE", "targetComponent": "a_customer_db"}
    failed = migrate.migrate_database(migrate_task(item))
    fix = poc5.diagnose(task(incident={**failed, "item": item}))
    assert fix["action"] == "APPLY_MAPPING" and fix["needsApproval"] is True
    assert fix["params"] == {"field": "date_of_birth", "fromFormat": "DD/MM/YYYY", "toFormat": "YYYY-MM-DD"}


def test_unknown_error_goes_to_a_person(mock_banks):
    fix = poc5.diagnose(task(incident={"componentId": "x", "errorCode": "DISK_FULL", "message": "no space"}))
    assert fix["action"] == "ESCALATE"


def test_reconciliation_finds_and_replays_missing_transactions(mock_banks):
    assert migrate.migrate_database(migrate_task(LEDGER))["ok"]
    check = poc6.compare_entity(task(entity="transactions", sourceBank="bank_b", targetBank="bank_a"))
    assert check["status"] == "MISMATCH" and len(check["recommendedAction"]["ids"]) == 12

    summary = poc6.summarise(task(batches={"cmp_transactions": check}, expected=1))
    assert summary["status"] == "NEEDS_REPAIR"
    incident = {"componentId": "records", "errorCode": "MISSING_RECORDS", "sourceBank": "bank_b", "targetBank": "bank_a",
                "details": {"repairs": summary["recommendedAction"]["repairs"]}}
    fix = poc5.diagnose(task(incident=incident))
    assert poc5.apply_fix(task(incident=incident, fix=fix))["message"] == "Replayed 12 transactions"
    recheck = poc6.compare_entity(task(entity="transactions", sourceBank="bank_b", targetBank="bank_a"))
    assert recheck["status"] == "MATCHED"


def test_high_risk_plan_needs_sign_off(mock_banks):
    plan = {"risk": "HIGH", "waves": [{"id": 1, "items": [{"componentId": "x", "risk": "HIGH", "action": "MIGRATE"}]}]}
    assert governance.policy_check(task(plan=plan))["verdict"] == "NEEDS_SIGN_OFF"
    low = {"risk": "LOW", "waves": [{"id": 1, "items": [{"componentId": "x", "risk": "LOW", "action": "MIGRATE"}]}]}
    assert governance.policy_check(task(plan=low))["verdict"] == "PASS"
