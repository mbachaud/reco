"""Mock driver: wraps a callable(static_context, observation) -> str.

Used by tests and by 'mock LLM' runs that push scripted decisions through the
full render -> respond -> parse -> journal pipeline with zero provider quota.
"""
from reco.gateway.drivers.base import DriverResult


class MockDriver:
    name = "mock"
    provider = "local"

    def __init__(self, respond):
        self._respond = respond

    def decide(self, static_context: str, observation: str, timeout_s: int) -> DriverResult:
        try:
            return DriverResult(text=self._respond(static_context, observation))
        except Exception as exc:  # a broken mock is a test bug — surface it
            return DriverResult(error="fatal", meta={"exception": repr(exc)})
