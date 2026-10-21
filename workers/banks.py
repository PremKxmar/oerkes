"""Bank adapters. Workers only talk to banks through this module, so moving
from the mock banks to Kinective's endpoints means adding one adapter here
and changing `adapter:` in the merger YAML.
"""
import httpx

from workers.settings import load_merger

TIMEOUT = httpx.Timeout(10.0)


class CallFailed(Exception):
    """A bank answered with an error the workflow should handle as data
    (bad token, bad field format). Network errors are not caught, so the
    task fails and Conductor retries it."""

    def __init__(self, error_code, message, details=None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


ERROR_CODES = {401: "AUTH_EXPIRED", 403: "AUTH_EXPIRED", 408: "TIMEOUT", 422: "FIELD_FORMAT", 504: "TIMEOUT"}


class MockBank:
    def __init__(self, name, base_url):
        self.name = name
        self.base_url = base_url.rstrip("/")

    def _call(self, method, path, body=None):
        r = httpx.request(method, f"{self.base_url}{path}", json=body, timeout=TIMEOUT)
        if r.status_code >= 400:
            try:
                payload = r.json()
            except ValueError:
                payload = {"message": r.text}
            code = ERROR_CODES.get(r.status_code, "UNKNOWN")
            if payload.get("error") == "field_format":
                code = "FIELD_FORMAT"
            raise CallFailed(code, payload.get("message", f"HTTP {r.status_code}"), {"httpStatus": r.status_code, **payload})
        return r.json()

    def inventory(self):
        return self._call("GET", "/inventory")["components"]

    def migrate(self, component_id, target_bank, target_component, action, wave):
        return self._call("POST", f"/components/{component_id}/migrate", {
            "targetBank": target_bank, "targetComponent": target_component, "action": action, "wave": wave,
        })

    def refresh_token(self, component_id):
        return self._call("POST", f"/components/{component_id}/token/refresh")

    def add_mapping(self, component_id, field, from_format, to_format):
        return self._call("POST", f"/components/{component_id}/mappings", {
            "field": field, "fromFormat": from_format, "toFormat": to_format,
        })

    def rollback(self, component_id):
        return self._call("POST", f"/components/{component_id}/rollback")

    def record_hashes(self, entity):
        return self._call("GET", f"/records/{entity}")["hashes"]

    def replay(self, entity, from_bank, ids):
        return self._call("POST", f"/records/{entity}/replay", {"fromBank": from_bank, "ids": ids})


class KinectiveBank(MockBank):
    """Placeholder until we have Kinective sandbox access. Fill in the same
    methods as MockBank against their API; nothing else needs to change."""

    def _call(self, method, path, body=None):
        raise NotImplementedError(f"Kinective adapter not wired yet ({method} {path}). Needs sandbox URL and auth.")


ADAPTERS = {"mock": MockBank, "kinective": KinectiveBank}


def bank(correlation_id, name):
    cfg = load_merger(correlation_id)["banks"][name]
    return ADAPTERS[cfg.get("adapter", "mock")](name, cfg["baseUrl"])
