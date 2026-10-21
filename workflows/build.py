"""Builds the 12 workflow definitions and the task definitions as JSON.

    python -m workflows.build          writes workflows/defs/*.json

The JSON files are what gets registered with Orkes (scripts/deploy.py), and
they can also be pasted into the Orkes UI. Edit this file, not the JSON.

Every workflow takes the shared input {eventType, correlationId, context,
payload} and returns {status, recommendedAction, risk, evidence,
correlationId}. Only tasks that work on all Conductor servers are used
(no HUMAN or BUSINESS_RULE), so the same files run on Orkes and on a local
Conductor in Docker. Approvals are WAIT tasks; complete them with
scripts/approve.py or from the Orkes UI.
"""
import json
import os
from pathlib import Path

OUT = Path(__file__).resolve().parent / "defs"
OWNER = os.getenv("OWNER_EMAIL", "orkes-poc@example.com")
CONTRACT_INPUTS = ["eventType", "correlationId", "context", "payload"]

CID = "${workflow.input.correlationId}"
CTX = "${workflow.input.context}"


# ---------- small helpers for task JSON ----------

def simple(name, ref=None, **inputs):
    return {"name": name, "taskReferenceName": ref or name, "type": "SIMPLE", "inputParameters": inputs}


def inline(ref, script, **inputs):
    """script is a JS function body; inputs are available as $.name."""
    return {"name": ref, "taskReferenceName": ref, "type": "INLINE",
            "inputParameters": {"evaluatorType": "graaljs", "expression": f"(function(){{ {script} }})()", **inputs}}


def switch(ref, expression, cases, default=None, **inputs):
    return {"name": ref, "taskReferenceName": ref, "type": "SWITCH", "evaluatorType": "graaljs",
            "expression": f"(function(){{ {expression} }})()", "inputParameters": inputs,
            "decisionCases": cases, "defaultCase": default or []}


def sub(name, ref, event_type, payload, optional=False, context=CTX):
    t = {"name": name, "taskReferenceName": ref, "type": "SUB_WORKFLOW",
         "subWorkflowParam": {"name": name, "version": 1},
         "inputParameters": {"eventType": event_type, "correlationId": CID, "context": context, "payload": payload}}
    if optional:
        t["optional"] = True
    return t


def dynamic_fork(ref, tasks_from):
    """Fan out over the {tasks, inputs} built by an INLINE task, then join."""
    return [
        {"name": ref, "taskReferenceName": ref, "type": "FORK_JOIN_DYNAMIC",
         "inputParameters": {"dynamicTasks": f"${{{tasks_from}.output.result.tasks}}",
                             "dynamicTasksInput": f"${{{tasks_from}.output.result.inputs}}"},
         "dynamicForkTasksParam": "dynamicTasks", "dynamicForkTasksInputParamName": "dynamicTasksInput"},
        {"name": f"{ref}_join", "taskReferenceName": f"{ref}_join", "type": "JOIN", "joinOn": []},
    ]


def fork_builder(ref, list_expr, workflow, event_type, ref_prefix, id_expr, payload_expr, **inputs):
    """INLINE task that turns a list into dynamic SUB_WORKFLOW tasks.
    The fork tasks are optional, so one failure does not stop the others."""
    script = f"""
      var list = {list_expr}; var tasks = []; var inputs = {{}};
      for (var i = 0; i < list.length; i++) {{
        var x = list[i]; var r = '{ref_prefix}_' + {id_expr};
        tasks.push({{name: '{workflow}', taskReferenceName: r, type: 'SUB_WORKFLOW', optional: true,
                    subWorkflowParam: {{name: '{workflow}', version: 1}}}});
        inputs[r] = {{eventType: '{event_type}', correlationId: $.correlationId, context: $.context,
                     payload: {payload_expr}}};
      }}
      return {{tasks: tasks, inputs: inputs, count: list.length}};"""
    return inline(ref, " ".join(script.split()), correlationId=CID, context=CTX, **inputs)


def approval(prefix, title, details, auto_expr="$.context.autoApprove === true", auto_value=True, **inputs):
    """WAIT for a person unless auto applies. Read the answer from
    ${<prefix>.output.result.approved}. A person completes the WAIT task with
    output {"approved": true|false, "by": "...", "comment": "..."}."""
    wait = {"name": f"{prefix}_wait", "taskReferenceName": f"{prefix}_wait", "type": "WAIT",
            "inputParameters": {"approvalTitle": title, "details": details}}
    gate = switch(f"{prefix}_gate", f"return ({auto_expr}) ? 'auto' : 'manual';", {"manual": [wait]},
                  context=CTX, **inputs)
    decision = inline(prefix, f"""
        if ({auto_expr}) return {{approved: {str(auto_value).lower()}, by: 'auto', comment: ''}};
        var w = $.wait || {{}};
        return {{approved: w.approved === true, by: w.by || 'unknown', comment: w.comment || ''}};""",
                      context=CTX, wait=f"${{{prefix}_wait.output}}", **inputs)
    return [gate, decision]


def contract_output(ref, inline=False):
    """Map a task's output to the workflow output. INLINE tasks nest it under result."""
    base = f"{ref}.output.result" if inline else f"{ref}.output"
    return {k: f"${{{base}.{k}}}" for k in ["status", "recommendedAction", "risk", "evidence", "correlationId"]}


def workflow(name, description, tasks, output, failure_workflow=None):
    wf = {"name": name, "description": description, "version": 1, "schemaVersion": 2,
          "ownerEmail": OWNER, "inputParameters": CONTRACT_INPUTS, "tasks": tasks,
          "outputParameters": output, "restartable": True, "timeoutPolicy": "ALERT_ONLY", "timeoutSeconds": 0}
    if failure_workflow:
        wf["failureWorkflow"] = failure_workflow
    return wf


def result_inline(ref, status_js, risk_js, evidence_js, action_js, prelude="", **inputs):
    """INLINE task that returns the shared contract. prelude runs first."""
    return inline(ref, f"""{prelude} return {{status: {status_js}, risk: {risk_js}, evidence: {evidence_js},
        recommendedAction: {action_js}, correlationId: $.correlationId}};""", correlationId=CID, **inputs)


P = "${workflow.input.payload"   # P + ".x}" -> ${workflow.input.payload.x}


# ---------- POC 2: stack assessment ----------

def poc2_assess_capability():
    match = simple("poc2_match_rule", "match_rule", correlationId=CID, capability=P + ".capability}",
                   source=P + ".source}", target=P + ".target}")
    agent = simple("poc2_compare_agent", "compare_agent", correlationId=CID, capability=P + ".capability}",
                   source=P + ".source}", target=P + ".target}")
    route = switch("rule_or_agent", "return $.matched ? 'rule' : 'agent';", {"agent": [agent]},
                   matched="${match_rule.output.matched}")
    answer = result_inline("answer", "'ASSESSED'", "a.risk", "[a.capability + ': ' + a.decision + ' (' + a.decidedBy + '), ' + a.reason]",
                           "{type: a.decision, assessment: a}", prelude="var a = $.rule || $.agent;",
                           rule="${match_rule.output.assessment}", agent="${compare_agent.output.assessment}")
    return workflow("poc2_assess_capability",
                    "POC 2: decide what to do with one capability. Config rules first, the compare agent otherwise.",
                    [match, route, answer], contract_output("answer", inline=True))


def poc2_stack_assessment():
    fetch = simple("poc2_fetch_inventories", "fetch_inventories", correlationId=CID,
                   acquirer=P + ".acquirer}", acquired=P + ".acquired}")
    build = fork_builder("assess_tasks", "$.capabilities", "poc2_assess_capability", "CAPABILITY_ASSESSMENT",
                         "assess", "x.capability", "x", capabilities="${fetch_inventories.output.capabilities}")
    plan = simple("poc2_build_wave_plan", "build_wave_plan", correlationId=CID, acquirer=P + ".acquirer}",
                  acquired=P + ".acquired}", assessments="${assess_fork_join.output}")
    return workflow("poc2_stack_assessment",
                    "POC 2: read both banks' inventories, assess every capability in parallel, and build a wave plan.",
                    [fetch, build, *dynamic_fork("assess_fork", "assess_tasks"), plan], contract_output("build_wave_plan"))


# ---------- Shared governance ----------

def shared_governance():
    check = simple("shared_policy_check", "policy_check", correlationId=CID, plan=P + ".plan}")
    sign_off = approval("sign_off", "Sign off the merger plan", "${policy_check.output.findings}",
                        auto_expr="$.context.autoApprove === true || $.verdict !== 'NEEDS_SIGN_OFF'",
                        verdict="${policy_check.output.verdict}")
    answer = result_inline(
        "decision",
        "($.verdict !== 'BLOCKED' && $.signOff.approved) ? 'APPROVED' : 'REJECTED'",
        "$.risk",
        "$.findings.concat(['Sign-off: ' + ($.verdict === 'NEEDS_SIGN_OFF' ? ($.signOff.approved ? 'approved by ' + $.signOff.by : 'rejected by ' + $.signOff.by) : 'not needed')])",
        "{type: 'NONE'}",
        verdict="${policy_check.output.verdict}", findings="${policy_check.output.findings}",
        risk="${policy_check.output.risk}", signOff="${sign_off.output.result}")
    return workflow("shared_governance", "Shared: check the plan against policy and get a sign-off when the risk needs one.",
                    [check, *sign_off, answer], contract_output("decision", inline=True))


# ---------- Migration of one component ----------

def migrate_component():
    common = dict(correlationId=CID, item=P + ".item}", sourceBank=P + ".sourceBank}",
                  targetBank=P + ".targetBank}", wave=P + ".wave}")
    cases = {
        "database": [simple("migrate_database", "step_database", **common)],
        "integration": [simple("migrate_integration", "step_integration", **common)],
        "infrastructure": [simple("migrate_infrastructure", "step_infrastructure", **common)],
    }
    route = switch("by_type", """
        var t = $.type;
        if (t === 'database') return 'database';
        if (t === 'api_integration' || t === 'file_transfer') return 'integration';
        if (t === 'infrastructure' || t === 'security' || t === 'monitoring') return 'infrastructure';
        return 'application';""", cases, default=[simple("migrate_application", "step_application", **common)],
                   type=P + ".item.type}")
    answer = result_inline(
        "outcome", "s.ok ? 'MIGRATED' : 'FAILED'", "s.ok ? 'LOW' : 'MEDIUM'",
        "[s.componentId + ': ' + s.message]",
        "s.ok ? {type: 'NONE', componentId: s.componentId} : {type: 'SELF_HEAL', componentId: s.componentId, errorCode: s.errorCode, message: s.message, details: s.details}",
        prelude="var s = [$.a, $.b, $.c, $.d].filter(function(o){ return o && o.componentId; })[0];",
        a="${step_database.output}", b="${step_integration.output}", c="${step_infrastructure.output}",
        d="${step_application.output}")
    return workflow("migrate_component",
                    "Move one Bank B component. Branches by type: database, integration, infrastructure, application.",
                    [route, answer], contract_output("outcome", inline=True))


# ---------- POC 5: self-heal one incident ----------

def poc5_self_heal():
    incident = P + ".incident}"
    diagnose = simple("poc5_diagnose", "diagnose", correlationId=CID, incident=incident)
    fix_approval = approval("fix_approval", "Approve the fix", "${diagnose.output}",
                            auto_expr="$.context.autoApprove === true || $.needsApproval !== true",
                            needsApproval="${diagnose.output.needsApproval}")
    apply = simple("poc5_apply_fix", "apply_fix", correlationId=CID, incident=incident, fix="${diagnose.output}")
    verify = simple("poc5_verify_fix", "verify_fix", correlationId=CID, incident=incident, fix="${diagnose.output}")
    after_apply = switch("fix_applied", "return $.applied ? 'verify' : 'skip';", {"verify": [verify]},
                         applied="${apply_fix.output.applied}")
    run_fix = switch("fix_approved", "return $.approved ? 'apply' : 'skip';", {"apply": [apply, after_apply]},
                     approved="${fix_approval.output.result.approved}")
    # A person fixes it by hand. Auto mode never pretends a person did this.
    escalation = approval("escalation", "Fix needed by a person", "${diagnose.output.reason}",
                          auto_expr="$.context.autoApprove === true", auto_value=False)
    route = switch("known_fix", "return $.action === 'ESCALATE' ? 'escalate' : 'runbook';",
                   {"escalate": escalation, "runbook": [*fix_approval, run_fix]}, action="${diagnose.output.action}")
    answer = result_inline(
        "outcome",
        "$.fix.action === 'ESCALATE' ? ($.person && $.person.approved ? 'RESOLVED_BY_PERSON' : 'NOT_HEALED') : ($.verify && $.verify.healed ? 'HEALED' : 'NOT_HEALED')",
        "$.fix.risk",
        "[$.fix.reason, $.approvalNote, $.apply ? $.apply.message : 'Fix not applied', $.verify ? $.verify.message : 'Not re-checked'].filter(function(x){ return x; })",
        "{type: ($.verify && $.verify.healed) || ($.person && $.person.approved) ? 'NONE' : 'ROLLBACK', componentId: $.incident.componentId, fix: $.fix.action}",
        incident=incident, fix="${diagnose.output}", apply="${apply_fix.output}", verify="${verify_fix.output}",
        person="${escalation.output.result}", approvalNote="${fix_approval.output.result.comment}")
    return workflow("poc5_self_heal", "POC 5: diagnose a failure, apply the runbook fix (with approval when needed), re-check.",
                    [diagnose, route, answer], contract_output("outcome", inline=True))


# ---------- POC 6: reconciliation ----------

def poc6_compare_batch():
    compare = simple("poc6_compare_entity", "compare_entity", correlationId=CID, entity=P + ".entity}",
                     sourceBank=P + ".sourceBank}", targetBank=P + ".targetBank}")
    return workflow("poc6_compare_batch", "POC 6: compare one entity (accounts, balances, ...) between the banks.",
                    [compare], contract_output("compare_entity"))


def poc6_reconcile():
    build = fork_builder("compare_tasks", "$.entities", "poc6_compare_batch", "RECON_BATCH", "cmp", "x",
                         "{entity: x, sourceBank: $.sourceBank, targetBank: $.targetBank}",
                         entities=P + ".entities}", sourceBank=P + ".sourceBank}", targetBank=P + ".targetBank}")
    summary = simple("poc6_summarise", "summarise", correlationId=CID, batches="${compare_fork_join.output}",
                     expected="${compare_tasks.output.result.count}")
    return workflow("poc6_reconcile", "POC 6: compare every entity for a wave in parallel and say whether repair is needed.",
                    [build, *dynamic_fork("compare_fork", "compare_tasks"), summary], contract_output("summarise"))


# ---------- verify_and_repair: POC 6 -> POC 5 -> POC 6, capped ----------

def verify_and_repair():
    recon_payload = {"entities": P + ".entities}", "sourceBank": P + ".sourceBank}",
                     "targetBank": P + ".targetBank}", "waveId": P + ".waveId}"}
    reconcile = sub("poc6_reconcile", "reconcile", "RECON_REQUEST", recon_payload)
    heal = sub("poc5_self_heal", "repair", "INCIDENT", {"incident": {
        "componentId": "records", "errorCode": "MISSING_RECORDS", "message": "Records missing after migration",
        "details": {"repairs": "${reconcile.output.recommendedAction.repairs}"},
        "sourceBank": P + ".sourceBank}", "targetBank": P + ".targetBank}", "wave": P + ".waveId}"}})
    repair_if_needed = switch(
        "needs_repair", "return ($.status === 'NEEDS_REPAIR' && $.round <= $.context.maxRepairRounds) ? 'repair' : 'done';",
        {"repair": [heal]}, status="${reconcile.output.status}", round="${repair_loop.output.iteration}", context=CTX)
    loop = {"name": "repair_loop", "taskReferenceName": "repair_loop", "type": "DO_WHILE",
            "evaluatorType": "graaljs",
            "loopCondition": "(function(){ return $.reconcile.status === 'NEEDS_REPAIR' && $.repair_loop.iteration <= $.context.maxRepairRounds; })()",
            "inputParameters": {"context": CTX},
            "loopOver": [reconcile, repair_if_needed]}
    review = approval("manual_review", "Reconciliation still failing after automatic repairs. Accept the wave?",
                      "${reconcile.output.evidence}", auto_value=False, status="${reconcile.output.status}")
    after = switch("still_broken", "return $.status === 'RECONCILED' ? 'ok' : 'review';", {"review": review},
                   status="${reconcile.output.status}")
    answer = result_inline(
        "verdict",
        "($.status === 'RECONCILED' || ($.review && $.review.approved)) ? 'VERIFIED' : 'FAILED'",
        "$.status === 'RECONCILED' ? 'LOW' : 'HIGH'",
        "trail",
        "$.status === 'RECONCILED' || ($.review && $.review.approved) ? {type: 'NONE'} : {type: 'ROLLBACK'}",
        prelude="""var trail = [];
          for (var n = 1; n <= $.loop.iteration; n++) {
            var r = $.loop['' + n] || {}; var c = r.reconcile || {};
            var found = (c.evidence || []).filter(function(e){ return e.indexOf('missing') >= 0 || e.indexOf('differ') >= 0; });
            trail.push('Check ' + n + ': ' + c.status + (found.length ? ' (' + found.join('; ') + ')' : ''));
            if (r.repair) trail.push('Repair ' + n + ': ' + r.repair.status + ', ' + (r.repair.evidence || []).slice(-2).join('; '));
          }
          if ($.review) trail.push('Manual review: ' + ($.review.approved ? 'accepted' : 'rejected') + ' by ' + $.review.by);""",
        status="${reconcile.output.status}", loop="${repair_loop.output}", review="${manual_review.output.result}")
    return workflow("verify_and_repair",
                    "Check a wave with POC 6, repair with POC 5, re-check. Stops after maxRepairRounds and asks a person.",
                    [loop, after, answer], contract_output("verdict", inline=True))


# ---------- rollback and failure events ----------

def rollback_wave():
    step = simple("poc1_rollback_wave", "rollback", correlationId=CID, wave=P + ".wave}",
                  sourceBank=P + ".sourceBank}", reason=P + ".reason}")
    return workflow("rollback_wave", "Undo every component of a wave, newest first.", [step], contract_output("rollback"))


def failure_to_event():
    step = simple("shared_publish_failure", "publish", workflowId="${workflow.input.workflowId}",
                  reason="${workflow.input.reason}", failureStatus="${workflow.input.failureStatus}",
                  failureTaskId="${workflow.input.failureTaskId}", failedWorkflow="${workflow.input.failedWorkflow}",
                  correlationId="${workflow.correlationId}")
    wf = workflow("failure_to_event", "Runs when a merger workflow fails and publishes a WORKFLOW_FAILED event.",
                  [step], contract_output("publish"))
    wf["inputParameters"] = ["workflowId", "reason", "failureStatus", "failureTaskId", "failedWorkflow"]
    return wf


# ---------- POC 1: run the plan wave by wave ----------

# Inside DO_WHILE, Conductor appends __<iteration> to forked task refs, so
# join output is looked up by the componentId in each result instead.
BY_COMPONENT = """function byComponent(join) { var m = {}; for (var k in (join || {})) {
  var v = join[k]; if (v && v.recommendedAction && v.recommendedAction.componentId) m[v.recommendedAction.componentId] = v; }
  return m; }"""


def poc1_execute_plan():
    src, tgt = P + ".plan.acquired}", P + ".plan.acquirer}"
    count = inline("wave_count", "return $.plan.waves.length;", plan=P + ".plan}")
    pick = inline("current_wave", "return $.plan.waves[$.i - 1];", plan=P + ".plan}", i="${wave_loop.output.iteration}")
    wave = "${current_wave.output.result}"

    change_board = approval("change_board", "Change board: approve this wave", wave)
    stop = {"name": "stop_rejected", "taskReferenceName": "stop_rejected", "type": "TERMINATE",
            "inputParameters": {"terminationStatus": "COMPLETED", "terminationReason": "Change board rejected the wave",
                                "workflowOutput": {"status": "STOPPED", "risk": "MEDIUM", "correlationId": CID,
                                                   "recommendedAction": {"type": "REPLAN"},
                                                   "evidence": ["Change board rejected wave ${current_wave.output.result.id}"]}}}
    gate = switch("wave_approved", "return $.approved ? 'go' : 'stop';", {"stop": [stop]},
                  approved="${change_board.output.result.approved}")

    migrations = fork_builder("migrate_tasks", "$.wave.items", "migrate_component", "COMPONENT_MIGRATE", "mig",
                              "x.componentId", "{item: x, sourceBank: $.src, targetBank: $.tgt, wave: $.wave.id}",
                              wave=wave, src=src, tgt=tgt)
    failures = inline("failures", BY_COMPONENT + """
        var out = byComponent($.results); var list = [];
        for (var i = 0; i < $.wave.items.length; i++) {
          var item = $.wave.items[i]; var r = out[item.componentId];
          if (!r || r.status !== 'MIGRATED') {
            var a = (r && r.recommendedAction) || {};
            list.push({componentId: item.componentId, item: item, errorCode: a.errorCode || 'UNKNOWN',
                       message: a.message || 'migrate_component did not finish', details: a.details || {},
                       sourceBank: $.src, targetBank: $.tgt, wave: $.wave.id});
          }
        }
        return list;""", wave=wave, results="${migrate_fork_join.output}", src=src, tgt=tgt)
    heal_tasks = fork_builder("heal_tasks", "$.failures", "poc5_self_heal", "INCIDENT", "heal", "x.componentId",
                              "{incident: x}", failures="${failures.output.result}")
    heal_branch = switch("any_failures", "return $.failures.length > 0 ? 'heal' : 'none';",
                         {"heal": [heal_tasks, *dynamic_fork("heal_fork", "heal_tasks")]},
                         failures="${failures.output.result}")
    health = inline("wave_health", BY_COMPONENT + """
        var heals = byComponent($.heals); var open = [];
        for (var i = 0; i < $.failures.length; i++) {
          var h = heals[$.failures[i].componentId];
          if (!h || (h.status !== 'HEALED' && h.status !== 'RESOLVED_BY_PERSON')) open.push($.failures[i].componentId);
        }
        return {healthy: open.length === 0, unresolved: open};""",
                    failures="${failures.output.result}", heals="${heal_fork_join.output}")
    verify = sub("verify_and_repair", "verify", "VERIFY_WAVE",
                 {"entities": "${current_wave.output.result.reconcile}", "sourceBank": src, "targetBank": tgt,
                  "waveId": "${current_wave.output.result.id}"})
    verify_branch = switch("needs_verify", "return ($.healthy && $.entities.length > 0) ? 'verify' : 'skip';",
                           {"verify": [verify]}, healthy="${wave_health.output.result.healthy}",
                           entities="${current_wave.output.result.reconcile}")
    verdict = inline("wave_verdict", """
        if (!$.healthy) return {pass: false, reason: 'Could not heal: ' + $.unresolved.join(', ')};
        if ($.entities.length > 0 && (!$.verify || $.verify.status !== 'VERIFIED'))
          return {pass: false, reason: 'Reconciliation failed after repairs'};
        return {pass: true, reason: ''};""",
                     healthy="${wave_health.output.result.healthy}", unresolved="${wave_health.output.result.unresolved}",
                     entities="${current_wave.output.result.reconcile}", verify="${verify.output}")
    close = simple("poc1_close_wave", "close_wave", correlationId=CID, wave=wave,
                   migrations="${migrate_fork_join.output}", heals="${heal_fork_join.output}",
                   verification="${verify.output}")
    rollback = sub("rollback_wave", "rollback", "ROLLBACK_REQUEST",
                   {"wave": wave, "sourceBank": src, "reason": "${wave_verdict.output.result.reason}"})
    fail = {"name": "stop_failed", "taskReferenceName": "stop_failed", "type": "TERMINATE",
            "inputParameters": {"terminationStatus": "FAILED",
                                "terminationReason": "Wave ${current_wave.output.result.id} rolled back: ${wave_verdict.output.result.reason}",
                                "workflowOutput": {"status": "ROLLED_BACK", "risk": "HIGH", "correlationId": CID,
                                                   "recommendedAction": {"type": "MANUAL_REVIEW"},
                                                   "evidence": "${rollback.output.evidence}"}}}
    finish = switch("close_or_rollback", "return $.ok ? 'close' : 'rollback';",
                    {"close": [close], "rollback": [rollback, fail]}, ok="${wave_verdict.output.result.pass}")

    loop = {"name": "wave_loop", "taskReferenceName": "wave_loop", "type": "DO_WHILE", "evaluatorType": "graaljs",
            "loopCondition": "(function(){ return $.wave_loop.iteration < $.waves; })()",
            "inputParameters": {"waves": "${wave_count.output.result}"},
            "loopOver": [pick, *change_board, gate, migrations, *dynamic_fork("migrate_fork", "migrate_tasks"),
                         failures, heal_branch, health, verify_branch, verdict, finish]}
    summary = simple("poc1_summarise_execution", "summarise_execution", correlationId=CID,
                     loop="${wave_loop.output}", risks=[P + ".plan.risk}"])
    return workflow("poc1_execute_plan",
                    "POC 1: for each wave, change-board approval, migrate in parallel, heal failures (POC 5), "
                    "verify (POC 6), then close or roll back.",
                    [count, loop, summary], {**contract_output("summarise_execution"),
                                             "waves": "${summarise_execution.output.waves}"},
                    failure_workflow="failure_to_event")


# ---------- POC 1: the hub ----------

def poc1_merger_orchestrator():
    payload = {"acquirer": P + ".acquirer}", "acquired": P + ".acquired}"}
    assess = sub("poc2_stack_assessment", "assess", "STACK_ASSESSMENT_REQUEST", payload)
    plan = "${assess.output.recommendedAction.plan}"
    govern = sub("shared_governance", "govern", "GOVERNANCE_REVIEW", {"plan": plan})
    reject = {"name": "stop_rejected", "taskReferenceName": "stop_rejected", "type": "TERMINATE",
              "inputParameters": {"terminationStatus": "COMPLETED", "terminationReason": "Plan rejected by governance",
                                  "workflowOutput": {"status": "REJECTED", "risk": "${govern.output.risk}",
                                                     "evidence": "${govern.output.evidence}", "correlationId": CID,
                                                     "recommendedAction": {"type": "REPLAN"}}}}
    gate = switch("plan_approved", "return $.status === 'APPROVED' ? 'go' : 'stop';", {"stop": [reject]},
                  status="${govern.output.status}")
    execute = sub("poc1_execute_plan", "execute", "WAVE_PLAN_EXECUTE", {"plan": plan}, optional=True)
    report = simple("poc1_cutover_report", "cutover_report", correlationId=CID, plan=plan,
                    execution="${execute.output}", executionError="${execute.reasonForIncompletion}")
    return workflow("poc1_merger_orchestrator",
                    "POC 1 hub: assess (POC 2), govern, run the waves (POC 5 and 6 inside), then report. "
                    "Modules never call each other; this workflow composes them.",
                    [assess, govern, gate, execute, report],
                    {**contract_output("cutover_report"), "waves": "${cutover_report.output.waves}"},
                    failure_workflow="failure_to_event")


WORKFLOWS = [poc1_merger_orchestrator, poc1_execute_plan, shared_governance, verify_and_repair,
             poc2_stack_assessment, poc2_assess_capability, poc5_self_heal, poc6_reconcile, poc6_compare_batch,
             migrate_component, rollback_wave, failure_to_event]


def task_defs():
    def td(name, description, timeout=120, response=60):
        return {"name": name, "description": description, "ownerEmail": OWNER, "retryCount": 2,
                "retryLogic": "EXPONENTIAL_BACKOFF", "retryDelaySeconds": 2, "timeoutSeconds": timeout,
                "responseTimeoutSeconds": response, "timeoutPolicy": "TIME_OUT_WF", "concurrentExecLimit": 0}
    return [
        td("poc2_fetch_inventories", "Read both banks' inventories and group them by capability"),
        td("poc2_match_rule", "Look up a fixed answer for a capability in the merger YAML"),
        td("poc2_compare_agent", "LangGraph agent that decides MIGRATE / REHOST / KEEP", timeout=300, response=180),
        td("poc2_build_wave_plan", "Group decisions into waves using the merger YAML"),
        td("shared_policy_check", "Check the plan against governance policy"),
        td("shared_publish_failure", "Publish a WORKFLOW_FAILED event"),
        td("migrate_database", "Copy a database to the acquirer"),
        td("migrate_integration", "Re-point an API integration or file transfer"),
        td("migrate_infrastructure", "Move infrastructure, certificates or monitoring"),
        td("migrate_application", "Move an application or identity store"),
        td("poc5_diagnose", "Pick a runbook fix for a failure"),
        td("poc5_apply_fix", "Apply the runbook fix"),
        td("poc5_verify_fix", "Re-check after the fix"),
        td("poc6_compare_entity", "Compare one entity's records between the banks"),
        td("poc6_summarise", "Combine entity checks into one reconciliation result"),
        td("poc1_close_wave", "Record a finished wave"),
        td("poc1_rollback_wave", "Undo a wave"),
        td("poc1_summarise_execution", "Summarise all waves"),
        td("poc1_cutover_report", "Final report with follow-up actions"),
    ]


def main():
    OUT.mkdir(exist_ok=True)
    for build in WORKFLOWS:
        wf = build()
        (OUT / f"{wf['name']}.json").write_text(json.dumps(wf, indent=2) + "\n")
    (OUT / "_taskdefs.json").write_text(json.dumps(task_defs(), indent=2) + "\n")
    print(f"Wrote {len(WORKFLOWS)} workflows and {len(task_defs())} task definitions to {OUT}")


if __name__ == "__main__":
    main()
