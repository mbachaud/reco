import pytest

from reco.engine.content import load_content
from reco.engine.mapgen import init_state


@pytest.fixture(scope="session")
def content():
    return load_content("slice")


@pytest.fixture
def state(content):
    return init_state(seed=42, content=content, agent_ids=["a1", "a2", "a3"])


def rejections(events, agent=None, code=None):
    out = [e for e in events if e["type"] == "rejected"]
    if agent is not None:
        out = [e for e in out if e["agent"] == agent]
    if code is not None:
        out = [e for e in out if e["code"] == code]
    return out


def of_type(events, kind):
    return [e for e in events if e["type"] == kind]
