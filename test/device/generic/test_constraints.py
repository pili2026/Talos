from core.device.generic.constraints_policy import ConstraintPolicy
from core.schema.constraint_schema import ConstraintConfig


class DummyLogger:
    def __init__(self):
        self.logs = []

    def warning(self, msg):
        self.logs.append(msg)


def test_constraints_allow_and_block():
    logger = DummyLogger()
    c = ConstraintPolicy({"RW_FREQ": ConstraintConfig(min=10, max=60)}, logger)
    assert c.allow("RW_FREQ", 10.0)
    assert c.allow("RW_FREQ", 60.0)
    assert not c.allow("RW_FREQ", 61.0)
    assert any("out of range" in m for m in logger.logs)
