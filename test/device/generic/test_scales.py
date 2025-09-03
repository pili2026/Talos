import pytest

from device.generic.scales import ScaleService


class DummyLogger:
    def warning(self, *a, **k):
        pass


async def _idx_reader_factory(values: dict):
    async def _reader(name: str) -> int:
        return values.get(name, -1)

    return _reader


@pytest.mark.asyncio
async def test_energy_auto_and_kwh():
    logger = DummyLogger()
    tables = {
        "energy_table": [1.0, 2.0, 3.0],
        "energy_post_multiplier": 0.001,
        "current_table": [0.01, 0.02],
        "voltage_table": [1.0, 2.0],
    }
    modes = {"kwh": {"mode": "fixed", "fixed_scale": 0.05}}
    svc = ScaleService(tables, modes, logger)

    idx_reader = await _idx_reader_factory({"SCALE_EnergyIndex": 2})
    energy = await svc.get_factor("energy_auto", idx_reader)  # 3.0 * 0.001 = 0.003
    assert energy == pytest.approx(0.003)

    kwh = await svc.get_factor("kwh", idx_reader)  # fixed 0.05
    assert kwh == pytest.approx(0.05)

    # cache hit path
    kwh2 = await svc.get_factor("kwh", idx_reader)
    assert kwh2 == pytest.approx(0.05)

    svc.invalidate(["kwh"])  # selective invalidation
    kwh3 = await svc.get_factor("kwh", idx_reader)
    assert kwh3 == pytest.approx(0.05)
