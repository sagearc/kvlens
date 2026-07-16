from pathlib import Path

from kvlens.traces import CodexTraces, Role

SAMPLE = Path(__file__).parent.parent / "examples" / "trace.sample.json"


def test_loads_sharegpt_shape():
    traces = CodexTraces.load(SAMPLE)
    assert len(traces) == 1
    conv = traces[0]
    assert len(conv.conversations) == 4


def test_from_alias_maps_to_role():
    conv = CodexTraces.load(SAMPLE)[0]
    # "from" in the JSON is exposed as the Role enum
    assert conv.conversations[0].role is Role.human
    assert conv.conversations[1].role is Role.gpt
    assert {m.role for m in conv.conversations} <= {Role.human, Role.gpt}


def test_values_present():
    conv = CodexTraces.load(SAMPLE)[0]
    assert all(m.value for m in conv.conversations)
