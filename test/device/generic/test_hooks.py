from core.device.generic.hooks import HookManager


class DummyScale:
    def __init__(self):
        self.invoked = []

    def invalidate(self, keys=None):
        self.invoked.append(tuple(keys or []))


def test_hook_string_match():
    s = DummyScale()
    hm = HookManager(["CFG_PT_1st"], logger=None, scale_service=s)
    hm.on_write("CFG_PT_1st", {"offset": 10})
    assert s.invoked == [tuple()]


def test_hook_object_match_registers():
    s = DummyScale()
    hm = HookManager([{"registers": ["A", "B"], "invalidate": ["scales.kwh", "scales.voltage"]}], None, s)
    hm.on_write("A", {"offset": 5})
    assert s.invoked == [("kwh", "voltage")]


def test_hook_object_match_offsets():
    s = DummyScale()
    hm = HookManager([{"offsets": [5, 6]}], None, s)
    hm.on_write("X", {"offset": 6})
    assert s.invoked == [tuple()]
