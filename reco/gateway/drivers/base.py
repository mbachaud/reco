"""Driver contract: decide(static_context, observation, timeout_s) -> DriverResult.

Stateless — all agent memory lives in the engine-persisted scratchpad.
`error` classification drives runner policy: `timeout` -> PE_TIMEOUT idle,
`rate_limit` -> global pause + retry, `transient` -> bounded retry,
`fatal` -> error outcome for the slot.
"""
import re
from dataclasses import dataclass, field

_RATE_LIMIT = re.compile(
    r"rate.?limit|too many requests|quota|overloaded|usage limit|\b429\b", re.IGNORECASE
)


@dataclass
class DriverResult:
    text: str | None = None
    error: str | None = None  # None | timeout | rate_limit | transient | fatal
    usage: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def classify_failure(*streams: str) -> str:
    """rate_limit if any stream matches the throttle patterns, else transient."""
    for stream in streams:
        if stream and _RATE_LIMIT.search(stream):
            return "rate_limit"
    return "transient"
