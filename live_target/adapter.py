"""
adapter.py — AgentTarget abstraction.

This is the piece that turns agent-redteam from "evaluate a system prompt
string via one Claude call" into "probe an actual running agent over HTTP
and observe what it really does." Scaled down from the full multi-auth
adapter to a single strategy (API-key header) for this proof of concept —
the interface is designed so additional auth strategies (OAuth, mTLS,
signed requests, session cookies) can be added as new subclasses without
touching the eval harness or probe engine.
"""

from abc import ABC, abstractmethod
import requests


class AgentTarget(ABC):
    """Anything the red-team harness can send a probe to and get a
    real response + a ground-truth log of what the agent actually did."""

    @abstractmethod
    def send(self, message: str, session_id: str, **context) -> dict:
        """Send `message` to the target agent.

        Returns a dict: {"reply": str, "tool_calls": list, "session_id": str}
        `tool_calls` is the ground truth — every tool the agent actually
        invoked, with real inputs and real outputs — independent of
        whatever the agent's text reply claims it did.
        """
        raise NotImplementedError


class HTTPAgentTarget(AgentTarget):
    """Drives a live agent behind an HTTP endpoint, authenticated via a
    static API key sent as a header. One of several auth strategies the
    full adapter layer supports; this PoC exercises just this one against
    a real running service."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30,
                 header_name: str = "X-API-Key", chat_path: str = "/chat"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.header_name = header_name
        self.chat_path = chat_path
        self.session = requests.Session()

    def send(self, message: str, session_id: str, **context) -> dict:
        payload = {
            "session_id": session_id,
            "message": message,
            **context,   # e.g. customer_email
        }
        headers = {self.header_name: self.api_key, "content-type": "application/json"}

        resp = self.session.post(
            f"{self.base_url}{self.chat_path}",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "reply": data.get("reply", ""),
            "tool_calls": data.get("tool_calls", []),
            "session_id": data.get("session_id", session_id),
        }
