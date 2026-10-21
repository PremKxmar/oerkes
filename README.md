# Merger tech-stack absorption on Orkes Conductor

POC for Kinective: when Bank A acquires Bank B, move Bank B's systems onto
Bank A's stack using Orkes workflows. That covers databases, but also
integrations, file transfers, identity, hosting, network, certificates,
monitoring and applications.

The four POCs from the design deck:

| POC | Workflow(s) | Job |
|---|---|---|
| 1 | `poc1_merger_orchestrator`, `poc1_execute_plan` | Hub. Runs the merger end to end, wave by wave, and writes the cutover report |
| 2 | `poc2_stack_assessment`, `poc2_assess_capability` | Reads both inventories, decides MIGRATE / REHOST / KEEP per capability (config rule or LangGraph agent), builds the wave plan |
| 5 | `poc5_self_heal` | Fixes a failure using a runbook (token refresh, field mapping, record replay), asks for approval when the runbook says so, escalates unknown errors to a person |
| 6 | `poc6_reconcile`, `poc6_compare_batch` | Compares accounts, balances and transactions between the banks after a wave |

Shared: `shared_governance` (policy check and sign-off), `verify_and_repair`
(POC 6 then POC 5, at most 3 rounds, then a person), `migrate_component`
(one component, branched by type), `rollback_wave`, `failure_to_event`.

Modules never call each other. The hub composes them, and every workflow
also runs on its own with the same input and output (see `contract/`).

## Layout

```
config/mergers/mrg-042.yaml   one file per merger: banks, rules, waves, policies, runbooks
contract/                     JSON Schemas for the shared input and output
workflows/build.py            generates the 12 workflow definitions
workflows/defs/*.json         generated JSON, registered by deploy.py, can be pasted into the Orkes UI
workers/                      Python workers, one file per module
agents/compare_agent.py       POC 2 LangGraph agent
mock_banks/                   mock Bank A and Bank B APIs with three scenarios
scripts/                      deploy, start, approve, show
tests/                        pytest, no server needed
```

## Run it locally

Needs Python 3.10+ and Docker.

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt
cp .env.example .env

docker run -d --name conductor -p 8080:8080 -p 1234:5000 conductoross/conductor:latest   # UI on :1234
.venv/bin/uvicorn mock_banks.server:app --port 8099          # terminal 1
.venv/bin/python -m workers.main                             # terminal 2

.venv/bin/python -m scripts.deploy
.venv/bin/python -m scripts.start --auto --scenario demo
.venv/bin/python -m scripts.show --wait
```

`--auto` skips approvals. Leave it out to approve each step yourself:

```bash
.venv/bin/python -m scripts.start --scenario demo
.venv/bin/python -m scripts.show --wait        # stops when something needs approval
.venv/bin/python -m scripts.approve            # see what is waiting
.venv/bin/python -m scripts.approve --yes --by Prem
```

You get asked for: plan sign-off (when plan risk is MEDIUM or above), a
change-board approval for each wave, and approval for any fix whose runbook
says `needsApproval: true`. Escalations always wait for a person, even with
`--auto`.

### Scenarios

`--scenario` resets the mock banks first.

- `happy`: everything migrates first time.
- `demo`: wave 2 goes wrong in three ways. Bill-pay returns 401 (POC 5
  refreshes the token), the customer DB rejects DD/MM/YYYY dates (POC 5 adds
  the mapping after approval), and the core ledger copy drops 12
  transactions (POC 6 finds them, POC 5 replays them, POC 6 checks again).
- `rollback`: like demo, but the token refresh fails. Wave 2 is rolled back,
  wave 1 stays, and `failure_to_event` publishes the failure.

### Run one module alone

```bash
.venv/bin/python -m scripts.start poc6_reconcile \
  --payload '{"entities": ["accounts", "transactions"], "sourceBank": "bank_b", "targetBank": "bank_a"}'
.venv/bin/python -m scripts.start poc5_self_heal --auto \
  --payload '{"incident": {"componentId": "b_billpay", "errorCode": "AUTH_EXPIRED", "message": "401", "sourceBank": "bank_b", "targetBank": "bank_a", "item": {"componentId": "b_billpay", "type": "api_integration", "action": "MIGRATE", "targetComponent": "a_billpay"}}}'
```

### Tests

```bash
.venv/bin/python -m pytest -q
```

They cover the workers against the mock banks in-process, and check that the
generated JSON is consistent: refs are unique, every SIMPLE task has a task
definition and a worker, and every sub-workflow exists.

## Run it on the Orkes cluster

1. In the Orkes UI create an application and an access key, and give the
   application permission to run workers and manage metadata. A UI login
   does not work for the API.
2. Put the URL, key and secret in `.env` (see `.env.example`). Keep `.env`
   out of git.
3. `python -m scripts.deploy`, then start the workers and mock banks as
   above. Workers poll the cluster, so they and the mock banks can stay on
   your laptop.

## A new merger

Copy `config/mergers/mrg-042.yaml` to `config/mergers/<new-id>.yaml`, change
the banks, rules, waves, policies and runbooks, and run
`scripts.start --merger <new-id>`. The workflows do not change.

## Connecting to Kinective

Workers only talk to banks through `workers/banks.py`. `KinectiveBank` is a
stub with the same methods as `MockBank`. Once we have sandbox access, fill
it in and set `adapter: kinective` and `baseUrl` for that bank in the YAML.

## Things to know

- Approvals are WAIT tasks, not HUMAN tasks. HUMAN needs a user form and has
  to be enabled on the cluster by Orkes. WAIT also runs on the open-source
  Conductor in Docker. To switch later, replace the WAIT in
  `approval()` in `workflows/build.py`.
- Rules live in the YAML, not in BUSINESS_RULE tasks, because a
  BUSINESS_RULE file has to be at a URL the cluster can reach. The waves
  and runbooks sections could move to BUSINESS_RULE sheets once hosted.
- Inside a DO_WHILE, Conductor adds `__1`, `__2` to the refs of forked
  tasks, and a task skipped in this round still returns its output from an
  earlier round. The hub matches results by componentId, and
  `poc1_close_wave` filters by the current wave, to handle both.
- The compare agent uses an LLM only when `OPENAI_API_KEY` is set on the
  worker machine. The OpenAI integration inside Orkes is separate. Without
  a key the agent uses its rules, so the demo runs offline.
