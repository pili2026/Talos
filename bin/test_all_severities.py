#!/usr/bin/env python3
"""
Test all severity levels for Telegram notifications
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv

from model.enum.alert_enum import AlertSeverity
from schema.alert_schema import AlertMessageModel
from util.factory.notifier_factory import build_notifiers_and_routing
from util.time_util import TIMEZONE_INFO

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logger = logging.getLogger("TestAllSeverities")


async def main():
    # Load environment variables
    env_path = project_root / ".env"
    load_dotenv(env_path)

    logger.info("=" * 80)
    logger.info("Testing All Severity Levels")
    logger.info("=" * 80)

    # Load notifiers
    config_path = project_root / "res" / "notifier_config.yml"

    try:
        notifiers, config = build_notifiers_and_routing(str(config_path))
        logger.info(f"✅ Loaded {len(notifiers)} notifiers")
    except Exception as e:
        logger.error(f"❌ Failed to load config: {e}")
        return

    # Find Telegram notifier
    telegram_notifier = next((n for n in notifiers if n.notifier_type == "TelegramNotifier"), None)

    if not telegram_notifier:
        logger.error("❌ Telegram notifier not found!")
        return

    logger.info(f"✅ Found TelegramNotifier (chat_id: {telegram_notifier.chat_id})")

    # Test cases with realistic messages
    test_cases = [
        (AlertSeverity.CRITICAL, "VFD Critical Failure - Emergency Stop Required", "VFD_CRIT_001"),
        (AlertSeverity.ERROR, "Temperature Sensor Error - Reading Out of Range (85°C)", "TEMP_ERR_002"),
        (AlertSeverity.WARNING, "Temperature High - Approaching Threshold (48°C / 50°C)", "TEMP_WARN_003"),
        (AlertSeverity.INFO, "System Started Successfully - All Devices Online", "SYS_INFO_004"),
        (AlertSeverity.RESOLVED, "VFD Restored - System Operating Normally", "VFD_RESOLVED_001"),
    ]

    success_count = 0

    for i, (severity, message, alert_code) in enumerate(test_cases, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"Test {i}/{len(test_cases)}: {severity.name}")
        logger.info(f"{'='*80}")

        # Create alert
        alert = AlertMessageModel(
            model="SD400",
            slave_id=8,
            level=severity,
            message=message,
            alert_code=alert_code,
            timestamp=datetime.now(TIMEZONE_INFO),
        )

        # Send alert
        try:
            success = await telegram_notifier.send(alert)

            if success:
                logger.info(f"✅ {severity.name}: SUCCESS")
                success_count += 1
            else:
                logger.error(f"❌ {severity.name}: FAILED")
        except Exception as e:
            logger.error(f"❌ {severity.name}: EXCEPTION - {e}")

        # Wait between messages
        if i < len(test_cases):
            logger.info("Waiting 3 seconds before next test...")
            await asyncio.sleep(3)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total Tests: {len(test_cases)}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {len(test_cases) - success_count}")

    if success_count == len(test_cases):
        logger.info("🎉 ALL TESTS PASSED!")
    else:
        logger.warning(f"⚠️ {len(test_cases) - success_count} tests failed")

    logger.info("=" * 80)
    logger.info("Check your Telegram group for all messages")
    logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
