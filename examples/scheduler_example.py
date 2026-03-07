"""
Example: MinuteOffsetScheduler with ADR and Water Pump rules.

ADR rule  – fires at minute :07 and :37 of every hour, only on weekdays,
            only between 08:00 and 22:00.
Water Pump – fires once a day at 02:00 (daily maintenance window).
"""

import asyncio
import logging
from datetime import datetime
from datetime import time as dt_time

from core.evaluator.time_evalutor import TimeControlEvaluator
from core.schema.time_control_schema import DeviceSchedule, TimeControlConfig, TimeInterval
from core.util.scheduler.minute_offset_scheduler import MinuteOffsetScheduler, ScheduleRule
from core.util.time_util import TIMEZONE_INFO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

async def adr_callback(now: datetime) -> None:
    logger.info(f"[ADR] Triggered at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    # Place ADR demand-response logic here
    await asyncio.sleep(0)


async def water_pump_callback(now: datetime) -> None:
    logger.info(f"[WaterPump] Daily maintenance triggered at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    # Place water-pump maintenance logic here
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Build evaluator
# ---------------------------------------------------------------------------

def build_evaluator() -> TimeControlEvaluator:
    config = TimeControlConfig(
        timezone="Asia/Taipei",
        work_hours={
            "ADR": DeviceSchedule(
                weekdays={1, 2, 3, 4, 5},
                intervals=[TimeInterval(start=dt_time(8, 0), end=dt_time(22, 0))],
            ),
            "WATER_PUMP": DeviceSchedule(
                weekdays={1, 2, 3, 4, 5, 6, 7},
                intervals=[TimeInterval(start=dt_time(0, 0), end=dt_time(23, 59))],
            ),
        },
    )
    return TimeControlEvaluator(config)


# ---------------------------------------------------------------------------
# Build rules
# ---------------------------------------------------------------------------

def build_rules() -> list[ScheduleRule]:
    adr_rule = ScheduleRule(
        name="ADR",
        callback=adr_callback,
        trigger_minutes=[7, 37],         # fire at :07 and :37 every hour
        intervals=[("08:00", "22:00")],  # only during operating hours
        weekdays=[1, 2, 3, 4, 5],        # weekdays only
        device_id="ADR",                 # checked against evaluator.allow()
    )

    water_pump_rule = ScheduleRule(
        name="WaterPump",
        callback=water_pump_callback,
        time="02:00",                    # once per day at 02:00
        # No device_id → evaluator.allow() is not called; always passes
    )

    return [adr_rule, water_pump_rule]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    evaluator = build_evaluator()
    rules = build_rules()
    scheduler = MinuteOffsetScheduler(rules=rules, evaluator=evaluator, tz=TIMEZONE_INFO)
    logger.info("Scheduler started. Press Ctrl+C to stop.")
    await scheduler.run()


if __name__ == "__main__":
    asyncio.run(main())
