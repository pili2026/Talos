from unittest.mock import Mock
import pytest

from evaluator.control_evaluator import ControlEvaluator
from schema.control_config_schema import ControlConfig

# ----------------------
# Fixtures
# ----------------------


@pytest.fixture
def make_evaluator() -> tuple[ControlEvaluator, str, str]:
    """
    Factory fixture to build a ControlEvaluator given a cfg_dict.
    Usage:
        evaluator, model, slave_id = make_evaluator(cfg_dict)
    """

    def _make(cfg_dict: dict, model: str = "SD400", slave_id: str = "1"):
        cfg = ControlConfig(root=cfg_dict)
        evaluator = ControlEvaluator(cfg)
        return evaluator, model, slave_id

    return _make


@pytest.fixture
def make_snapshot():
    """
    Simple fixture to construct snapshot dict.
    Usage:
        snapshot = make_snapshot(AIn01=41.0, AIn03=3.5)
    """

    def _make(**kwargs):
        return dict(kwargs)

    return _make


@pytest.fixture
def make_config():
    """
    Factory fixture to build a minimal cfg_dict for a single instance with one or more controls.
    Usage:
        cfg_dict = make_config("SD400", "1", [control1, control2])
    Where control is a dict containing at least {name, code, priority, composite, action}
    """

    def _make(model: str, slave_id: str, controls: list[dict]):
        return {model: {"instances": {slave_id: {"controls": controls}}}}

    return _make


@pytest.fixture
def mock_control_config():
    """Create mock ControlConfig for testing"""
    return Mock(spec=ControlConfig)


@pytest.fixture
def control_evaluator(mock_control_config):
    """Create ControlEvaluator with mocked dependencies"""
    evaluator = ControlEvaluator(mock_control_config)
    evaluator.composite_evaluator = Mock()
    return evaluator
