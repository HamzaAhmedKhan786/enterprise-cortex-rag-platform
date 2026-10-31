"""Purpose-specific agents: deterministic authorization and tools, audited by LangGraph.

These agents intentionally do not ask an LLM to decide charges, malware verdicts,
access control or data migrations. Carol delegates language work to the RAG graph.
"""
import os
import secrets
import time
from typing import TypedDict

from cortex import store

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"


class ModuleState(TypedDict, total=False):
    owner: str
    action: str
    parameters: dict
    result: object
    steps: list


class ModuleAgent:
    name = "module"

    def tools(self):
        raise NotImplementedError

    def run(self, owner, action, **parameters):
        from langgraph.graph import END, StateGraph
        tools = self.tools()
        def authorize(state):
            with store.connection() as db:
                exists = db.execute("SELECT 1 FROM users WHERE id=?", (state["owner"],)).fetchone()
            if not exists or state["action"] not in tools:
                raise ValueError("Unknown workspace or unsupported agent action.")
            return {"steps": [{"agent": self.name, "status": "authorized", "detail": "Registered deterministic tool; account-scoped request"}]}
        def execute(state):
            result = tools[state["action"]](state["owner"], **state["parameters"])
            return {"result": result, "steps": state["steps"] + [{"agent": self.name, "status": "completed", "detail": "Tool completed; content and credentials omitted from tracking"}]}
        graph = StateGraph(ModuleState)
        graph.add_node("authorize", authorize)
        graph.add_node("execute", execute)
        graph.set_entry_point("authorize")
        graph.add_edge("authorize", "execute")
        graph.add_edge("execute", END)
        started, run_id = time.perf_counter(), secrets.token_hex(12)
        try:
            state = graph.compile().invoke({"owner": owner, "action": action, "parameters": parameters}, config={"recursion_limit": 4})
            store.save_run(owner, run_id, self.name, "completed", time.perf_counter() - started, state["steps"])
            return state["result"]
        except Exception:
            with store.connection() as db:
                exists = db.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone()
            if exists:
                store.save_run(owner, run_id, self.name, "failed", time.perf_counter() - started, [{"agent": self.name, "status": "failed", "detail": "Tool rejected/unavailable; no payload captured"}])
            raise


class SubscriptionAgent(ModuleAgent):
    name = "subscription_agent"
    def tools(self):
        from cortex import billing
        return {"checkout": billing.checkout, "portal": billing.portal, "refresh": billing.refresh}


class SecurityAgent(ModuleAgent):
    name = "security_agent"
    def tools(self):
        from cortex import security
        return {"posture": security.posture, "preferences": store.set_preferences}


class MigrationAgent(ModuleAgent):
    name = "snowflake_agent"
    def tools(self):
        from cortex import warehouse
        return {"check": warehouse.check, "export": warehouse.export_dataset, "import": warehouse.import_table}


class LogisticsAgent(ModuleAgent):
    name = "logistics_agent"
    def tools(self):
        from cortex import logistics
        return {"fetch": logistics.fetch, "assign": lambda actor, target_owner, plan_id: logistics.assign(actor, target_owner, plan_id)}


class UploadAgent(ModuleAgent):
    name = "upload_guardian_agent"
    def tools(self):
        from cortex.uploads import secure_ingest
        return {"scan_and_register": secure_ingest}


class CarolAgent(ModuleAgent):
    name = "carol_agent"
    def tools(self):
        from cortex.carol import ask
        return {"ask": ask}


class ObservabilityAgent(ModuleAgent):
    name = "observability_agent"
    def tools(self):
        from cortex import observability
        return {"verify_langfuse": observability.check_langfuse, "evaluate": observability.evaluation_smoke}
