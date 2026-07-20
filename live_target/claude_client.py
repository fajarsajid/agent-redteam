"""
claude_client.py — Thin wrapper around the Anthropic Messages API used by
the live agent target and the live evaluation harness.

Supports a MOCK mode (no API key required) so the plumbing — the HTTP
target, the adapter, the ground-truth tool-call verification, and the
tests — can all be exercised and CI-checked without live credentials.
This mirrors the existing repo's `test_redteam.py` pattern of mocked
API tests.
"""

import json
import os
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-20250514"


class ClaudeClient:
    """Calls the real Anthropic API, unless `mock_fn` is supplied, in which
    case every call is routed through the mock instead. This lets callers
    (agent_server, run_live_eval) be written once and run in either mode.
    """

    def __init__(self, api_key: str = None, model: str = DEFAULT_MODEL, mock_fn=None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.mock_fn = mock_fn
        if not self.mock_fn and not self.api_key:
            raise RuntimeError(
                "No ANTHROPIC_API_KEY set and no mock_fn provided. "
                "Set the env var for live runs, or pass mock_fn=... for offline/dev/test runs."
            )
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            })

    def messages_create(self, system: str, messages: list, tools: list = None, max_tokens: int = 1024):
        """Returns the raw Anthropic `content` block list, exactly as the
        live API would. In mock mode, `mock_fn(system, messages, tools)`
        must return that same shape.
        """
        if self.mock_fn:
            return self.mock_fn(system, messages, tools)

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        resp = self.session.post(ANTHROPIC_API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("content", [])
