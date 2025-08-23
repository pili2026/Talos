import pytest

from model.control_model import ControlActionType


@pytest.mark.asyncio
async def test_when_turn_on_and_already_on_result_skip_write(make_executor, make_action, make_device, caplog):
    # Arrange
    executor, fake_device_manager = make_executor()
    dev = make_device(registers={"RW_ON_OFF": {"writable": True}}, initial_values={"RW_ON_OFF": 1}, support_onoff=True)
    fake_device_manager.add("SD400", "1", dev)

    action = make_action(
        type=ControlActionType.TURN_ON, model="SD400", slave_id="1", target=None, value=None, reason="turn on requested"
    )

    # Act
    await executor.execute([action])

    # Assert
    # no write_on_off action
    assert ("RW_ON_OFF", 1) not in dev._writes
    # INFO level already enabled by conftest's autouse fixture
    assert any("[SKIP]" in rec.message and "already 1" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_when_turn_off_and_current_is_on_result_write_on_off(make_executor, make_action, make_device):
    # Arrange
    executor, fake_device_manager = make_executor()
    dev = make_device(registers={"RW_ON_OFF": {"writable": True}}, initial_values={"RW_ON_OFF": 1}, support_onoff=True)
    fake_device_manager.add("SD400", "1", dev)

    action = make_action(
        type=ControlActionType.TURN_OFF,
        model="SD400",
        slave_id="1",
        target=None,
        value=None,
        reason="turn off requested",
    )

    # Act
    await executor.execute([action])

    # Assert
    assert ("RW_ON_OFF", 0) in dev._writes
    assert dev._values["RW_ON_OFF"] == 0


@pytest.mark.asyncio
async def test_when_onoff_read_returns_float_one_result_skip_write(make_executor, make_action, make_device, caplog):
    """Reading back 1.0 should also be treated as ON ( _normalize_on_off_state in effect )"""
    # Arrange
    executor, fake_device_manager = make_executor()
    dev = make_device(
        registers={"RW_ON_OFF": {"writable": True}}, initial_values={"RW_ON_OFF": 1.0}, support_onoff=True
    )
    fake_device_manager.add("SD400", "2", dev)

    action = make_action(
        type=ControlActionType.TURN_ON, model="SD400", slave_id="2", target=None, value=None, reason="float one"
    )

    # Act
    await executor.execute([action])

    # Assert
    assert ("RW_ON_OFF", 1) not in dev._writes
    assert any("[SKIP]" in rec.message and "already 1" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_when_set_frequency_target_missing_on_device_result_skip(make_executor, make_action, make_device, caplog):
    # Arrange
    executor, fake_device_manager = make_executor()
    dev = make_device(registers={"RW_DO": {"writable": True}})  # without RW_HZ
    fake_device_manager.add("SD400", "3", dev)

    action = make_action(
        type=ControlActionType.SET_FREQUENCY, model="SD400", slave_id="3", target="RW_HZ", value=45.0, reason="set hz"
    )

    # Act
    await executor.execute([action])

    # Assert
    assert not dev._writes
    assert any("[SKIP]" in rec.message and "no such register: RW_HZ" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_when_target_not_writable_result_skip(make_executor, make_action, make_device, caplog):
    # Arrange
    executor, fake_device_manager = make_executor()
    dev = make_device(registers={"RW_HZ": {"writable": False}}, initial_values={"RW_HZ": 40.0})
    fake_device_manager.add("SD400", "4", dev)

    action = make_action(
        type=ControlActionType.SET_FREQUENCY,
        model="SD400",
        slave_id="4",
        target="RW_HZ",
        value=45.0,
        reason="not writable",
    )

    # Act
    await executor.execute([action])

    # Assert
    assert not dev._writes
    assert any("[SKIP]" in rec.message and "is not writable" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_when_current_value_equals_requested_with_tolerance_result_skip(
    make_executor, make_action, make_device, caplog
):
    # Arrange
    executor, fake_device_manager = make_executor()
    dev = make_device(registers={"RW_HZ": {"writable": True}}, initial_values={"RW_HZ": 45.0})
    fake_device_manager.add("SD400", "5", dev)

    action = make_action(
        type=ControlActionType.SET_FREQUENCY, model="SD400", slave_id="5", target="RW_HZ", value=45.0, reason="equal"
    )

    # Act
    await executor.execute([action])

    # Assert
    assert not dev._writes
    assert any("[SKIP]" in rec.message and "already 45.0" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_when_read_value_fails_result_still_try_write(make_executor, make_action, make_device, caplog):
    # Arrange
    executor, fake_device_manager = make_executor()
    dev = make_device(registers={"RW_HZ": {"writable": True}}, initial_values={"RW_HZ": 40.0})
    dev.fail_reads.add("RW_HZ")  # simulate read failure
    fake_device_manager.add("SD400", "6", dev)

    action = make_action(
        type=ControlActionType.SET_FREQUENCY,
        model="SD400",
        slave_id="6",
        target="RW_HZ",
        value=46.0,
        reason="read fail then write",
    )

    # Act
    await executor.execute([action])

    # Assert
    assert ("RW_HZ", 46.0) in dev._writes
    assert any("read RW_HZ failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_when_device_not_found_result_skip(make_executor, make_action, caplog):
    executor, fake_device_manager = make_executor()
    # no device added

    # Arrange
    action = make_action(
        type=ControlActionType.TURN_ON, model="SD400", slave_id="999", target=None, value=None, reason="device missing"
    )

    # Act
    await executor.execute([action])

    # Assert
    assert any("[SKIP]" in rec.message and "Device SD400_999 not found" in rec.message for rec in caplog.records)
