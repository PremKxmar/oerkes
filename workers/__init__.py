"""Workers for the merger POC. Each module maps to one owner:

poc1.py        hub, wave close-out, rollback, cutover report
poc2.py        stack assessment (agent lives in agents/compare_agent.py)
poc5.py        self-heal
poc6.py        reconciliation
migrate.py     per-type migration steps used by migrate_component
governance.py  shared policy check and failure events
"""
