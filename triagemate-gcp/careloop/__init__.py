"""CareLoop.

ADK discovers the agent by importing this package and looking for
`root_agent`, so `from . import agent` has to be here. But the triage
engine must stay usable without ADK installed -- the tests and the CLI
smoke test import careloop.engine directly and should not need a Gemini
dependency to run. Hence the guard.
"""

try:
    from . import agent  # noqa: F401
except ImportError as exc:  # pragma: no cover
    if "google.adk" not in str(exc):
        raise
    agent = None  # engine-only mode; pip install google-adk to enable the agent
