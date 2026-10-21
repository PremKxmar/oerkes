"""Seed data for the two mock banks.

Bank A is the acquirer (target stack). Bank B is the bank being absorbed.
The inventory covers more than databases on purpose: infrastructure,
identity, file transfer, certificates and monitoring all have to move too.
"""
import random

BANK_A_INVENTORY = [
    {"id": "a_core_ledger_db", "name": "Core ledger (PostgreSQL 16)", "type": "database", "capability": "core_ledger", "criticality": "critical"},
    {"id": "a_customer_db", "name": "Customer master (PostgreSQL 16)", "type": "database", "capability": "customer_data", "criticality": "critical"},
    {"id": "a_loan_origination", "name": "Loan origination system v7", "type": "application", "capability": "loan_origination", "criticality": "high"},
    {"id": "a_online_banking", "name": "Online banking portal", "type": "application", "capability": "online_banking", "criticality": "high"},
    {"id": "a_billpay", "name": "Bill-pay API gateway", "type": "api_integration", "capability": "bill_pay", "criticality": "high"},
    {"id": "a_card_processor", "name": "Card processing API", "type": "api_integration", "capability": "card_processing", "criticality": "high"},
    {"id": "a_ach_gateway", "name": "ACH payments API", "type": "api_integration", "capability": "ach_payments", "criticality": "high"},
    {"id": "a_entra_id", "name": "Cloud directory (SSO)", "type": "identity", "capability": "identity", "criticality": "high"},
    {"id": "a_cloud_hosting", "name": "Cloud hosting (Kubernetes)", "type": "infrastructure", "capability": "hosting", "criticality": "high"},
    {"id": "a_sdwan", "name": "SD-WAN branch network", "type": "infrastructure", "capability": "network", "criticality": "medium"},
    {"id": "a_cert_manager", "name": "Certificate manager", "type": "security", "capability": "certificates", "criticality": "medium"},
    {"id": "a_observability", "name": "Logging and monitoring stack", "type": "monitoring", "capability": "monitoring", "criticality": "medium"},
]

BANK_B_INVENTORY = [
    {"id": "b_core_ledger_db", "name": "Core ledger (Oracle 12c)", "type": "database", "capability": "core_ledger", "criticality": "critical"},
    {"id": "b_customer_db", "name": "Customer master (SQL Server 2014)", "type": "database", "capability": "customer_data", "criticality": "critical"},
    {"id": "b_loan_origination", "name": "Loan origination system v4", "type": "application", "capability": "loan_origination", "criticality": "high"},
    {"id": "b_online_banking", "name": "Online banking portal", "type": "application", "capability": "online_banking", "criticality": "high"},
    {"id": "b_wire_desk", "name": "Wire transfer desk app", "type": "application", "capability": "wire_transfers", "criticality": "high"},
    {"id": "b_billpay", "name": "Bill-pay integration", "type": "api_integration", "capability": "bill_pay", "criticality": "high"},
    {"id": "b_card_processor", "name": "Card processor link", "type": "api_integration", "capability": "card_processing", "criticality": "high"},
    {"id": "b_ach_sftp", "name": "Nightly ACH file drop (SFTP)", "type": "file_transfer", "capability": "ach_payments", "criticality": "high"},
    {"id": "b_active_directory", "name": "On-prem Active Directory", "type": "identity", "capability": "identity", "criticality": "high"},
    {"id": "b_vmware_cluster", "name": "VMware cluster (data centre)", "type": "infrastructure", "capability": "hosting", "criticality": "high"},
    {"id": "b_branch_vpn", "name": "Branch VPN", "type": "infrastructure", "capability": "network", "criticality": "medium"},
    {"id": "b_tls_certs", "name": "TLS certificates", "type": "security", "capability": "certificates", "criticality": "medium"},
    {"id": "b_log_collector", "name": "Syslog collector", "type": "monitoring", "capability": "monitoring", "criticality": "low"},
]


def bank_b_records(seed=42):
    """Accounts, balances, transactions and customers held by Bank B."""
    rng = random.Random(seed)
    customers, accounts, balances, transactions = {}, {}, {}, {}
    for c in range(1, 26):
        cid = f"CUS-B-{c:04d}"
        customers[cid] = {
            "id": cid,
            "name": f"Customer {c}",
            "date_of_birth": f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1950, 2002)}",
        }
    for a in range(1, 41):
        aid = f"ACC-B-{a:04d}"
        accounts[aid] = {
            "id": aid,
            "customerId": f"CUS-B-{rng.randint(1, 25):04d}",
            "type": rng.choice(["checking", "savings", "loan"]),
        }
        balances[aid] = {"id": aid, "amount": 0.0}
    for t in range(1, 241):
        tid = f"TXN-B-{t:05d}"
        aid = f"ACC-B-{rng.randint(1, 40):04d}"
        amount = round(rng.uniform(-500, 1500), 2)
        transactions[tid] = {"id": tid, "accountId": aid, "amount": amount, "date": f"2026-09-{rng.randint(1, 30):02d}"}
        balances[aid]["amount"] = round(balances[aid]["amount"] + amount, 2)
    return {"customers": customers, "accounts": accounts, "balances": balances, "transactions": transactions}
