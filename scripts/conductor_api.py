"""Minimal Conductor/Orkes REST client used by the scripts.

Orkes needs an application key (Settings > Applications > create key) in
CONDUCTOR_AUTH_KEY / CONDUCTOR_AUTH_SECRET. A UI username and password does
not work for the API. A local Conductor needs no key.
"""
import os

import httpx

from scripts.env import load_env

load_env()


class Conductor:
    def __init__(self):
        self.base = os.getenv("CONDUCTOR_SERVER_URL", "http://localhost:8080/api").rstrip("/")
        self.http = httpx.Client(timeout=30)
        key, secret = os.getenv("CONDUCTOR_AUTH_KEY"), os.getenv("CONDUCTOR_AUTH_SECRET")
        if key and secret:
            r = self.http.post(f"{self.base}/token", json={"keyId": key, "keySecret": secret})
            r.raise_for_status()
            self.http.headers["X-Authorization"] = r.json()["token"]

    def call(self, method, path, **kwargs):
        r = self.http.request(method, f"{self.base}{path}", **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else r.text

    def register_task_defs(self, defs):
        return self.call("POST", "/metadata/taskdefs", json=defs)

    def update_task_def(self, d):
        return self.call("PUT", "/metadata/taskdefs", json=d)

    def put_workflows(self, defs):
        return self.call("PUT", "/metadata/workflow", json=defs)

    def start(self, name, body, correlation_id):
        return self.call("POST", f"/workflow/{name}", params={"correlationId": correlation_id}, json=body)

    def workflow(self, workflow_id):
        return self.call("GET", f"/workflow/{workflow_id}", params={"includeTasks": "true"})

    def complete_task(self, workflow_id, task_id, output):
        return self.call("POST", "/tasks", json={"workflowInstanceId": workflow_id, "taskId": task_id,
                                                  "status": "COMPLETED", "outputData": output})

    def tree(self, workflow_id, depth=0):
        """Yield (depth, workflow) for a workflow and all its sub-workflows."""
        wf = self.workflow(workflow_id)
        yield depth, wf
        for t in wf.get("tasks", []):
            child = t.get("subWorkflowId") or (t.get("outputData") or {}).get("subWorkflowId")
            if t.get("taskType") == "SUB_WORKFLOW" and child:
                yield from self.tree(child, depth + 1)
