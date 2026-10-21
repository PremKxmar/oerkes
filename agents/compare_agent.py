"""POC 2 compare agent (bring your own agent, run as an Orkes worker).

For one capability it looks at what Bank B runs and what Bank A runs, and
decides what to do with Bank B's components:

  MIGRATE   move B's data/users onto A's equivalent, then retire B's
  REHOST    A has nothing equivalent, so B's component moves onto A's hosting
  KEEP      leave it where it is for now (needs a person to revisit)

Graph:  profile -> decide (LLM if OPENAI_API_KEY is set, rules otherwise) -> check
If the LLM answer is unusable, `check` falls back to the rule answer.
"""
import json
import os
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

DECISIONS = {"MIGRATE", "REHOST", "KEEP"}
RISKS = {"LOW", "MEDIUM", "HIGH"}


class AgentState(TypedDict, total=False):
    capability: str
    source: list
    target: list
    facts: dict
    decision: str
    risk: str
    reason: str
    decided_by: str
    llm_error: Optional[str]


def profile(state: AgentState) -> AgentState:
    source, target = state["source"], state["target"]
    source_types = sorted({c["type"] for c in source})
    target_types = sorted({c["type"] for c in target})
    return {"facts": {
        "hasEquivalent": bool(target),
        "sameType": bool(target) and source_types == target_types,
        "sourceTypes": source_types,
        "targetTypes": target_types,
        "critical": any(c.get("criticality") == "critical" for c in source),
        "sourceNames": [c["name"] for c in source],
        "targetNames": [c["name"] for c in target],
    }}


def rule_answer(facts):
    if not facts["hasEquivalent"]:
        return "REHOST", "MEDIUM", "Bank A has no equivalent, so Bank B's component moves onto Bank A's hosting as is"
    if not facts["sameType"]:
        return "MIGRATE", "HIGH", (f"Bank A does this with {', '.join(facts['targetTypes'])} instead of "
                                   f"{', '.join(facts['sourceTypes'])}, so the interface has to be converted")
    if facts["critical"]:
        return "MIGRATE", "MEDIUM", "Both banks have it; critical data moves to Bank A's system and needs reconciliation"
    return "MIGRATE", "LOW", "Both banks have it; Bank B's users move to Bank A's system and B's copy is retired"


def decide(state: AgentState) -> AgentState:
    if not os.getenv("OPENAI_API_KEY"):
        decision, risk, reason = rule_answer(state["facts"])
        return {"decision": decision, "risk": risk, "reason": reason, "decided_by": "agent-rules"}
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
        prompt = (
            "You are helping plan a bank merger. Bank A is acquiring Bank B.\n"
            f"Capability: {state['capability']}\nFacts: {json.dumps(state['facts'])}\n"
            "Choose what to do with Bank B's components: MIGRATE, REHOST or KEEP. "
            "Rate the risk LOW, MEDIUM or HIGH. Reply with JSON only: "
            '{"decision": "...", "risk": "...", "reason": "one sentence"}'
        )
        answer = json.loads(llm.invoke(prompt).content.strip().strip("`").removeprefix("json"))
        return {"decision": answer.get("decision"), "risk": answer.get("risk"),
                "reason": answer.get("reason", ""), "decided_by": "agent-llm"}
    except Exception as e:  # a bad LLM reply should not fail the merger
        return {"decision": None, "llm_error": str(e)}


def check(state: AgentState) -> AgentState:
    if state.get("decision") in DECISIONS and state.get("risk") in RISKS:
        return {}
    decision, risk, reason = rule_answer(state["facts"])
    note = f" (LLM answer unusable: {state.get('llm_error') or 'invalid fields'})"
    return {"decision": decision, "risk": risk, "reason": reason + note, "decided_by": "agent-rules"}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("profile", profile)
    g.add_node("decide", decide)
    g.add_node("check", check)
    g.set_entry_point("profile")
    g.add_edge("profile", "decide")
    g.add_edge("decide", "check")
    g.add_edge("check", END)
    return g.compile()


GRAPH = build_graph()


def compare(capability, source, target):
    out = GRAPH.invoke({"capability": capability, "source": source, "target": target})
    return {"decision": out["decision"], "risk": out["risk"], "reason": out["reason"], "decidedBy": out["decided_by"]}
