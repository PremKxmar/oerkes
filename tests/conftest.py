from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mock_banks import server
from workers import banks

MOCK = "http://localhost:8099"


@pytest.fixture
def mock_banks(monkeypatch):
    """Point the bank adapters at the mock API in-process (no server needed)."""
    client = TestClient(server.app)
    server.reset("demo")

    def request(method, url, json=None, timeout=None):
        return client.request(method, url.removeprefix(MOCK), json=json)

    monkeypatch.setattr(banks.httpx, "request", request)
    return server


def task(**inputs):
    """Stand-in for a Conductor Task: workers only read input_data."""
    return SimpleNamespace(input_data={"correlationId": "mrg-042", **inputs})
