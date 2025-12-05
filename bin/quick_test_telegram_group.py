import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv

from core.model.enum.alert_enum import AlertSeverity
from core.schema.alert_schema import AlertMessageModel
from core.util.notifier.telegram_notifier import TelegramNotifier
from core.util.time_util import TIMEZONE_INFO

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logger = logging.getLogger("QuickTest")


async def main():
    load_dotenv()

    import os

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    logger.info(f"Bot Token: {bot_token[:20]}...")
    logger.info(f"Chat ID: {chat_id}")

    if not bot_token or not chat_id:
        logger.error("Bot Token or Chat ID not set!")
        return

    # Create notifier
    notifier = TelegramNotifier(
        bot_token=bot_token, chat_id=chat_id, priority=2, enabled=True, timeout_sec=5.0, parse_mode="HTML"
    )

    # Create test alert
    alert = AlertMessageModel(
        model="TEST_DEVICE",
        slave_id=1,
        level=AlertSeverity.WARNING,
        message="This is a test alert from Talos System",
        alert_code="TEST_001",
        timestamp=datetime.now(TIMEZONE_INFO),
    )

    logger.info("Sending test alert...")
    success = await notifier.send(alert)

    if success:
        logger.info("Test SUCCESS! Check your Telegram!")
    else:
        logger.error("Test FAILED!")


if __name__ == "__main__":
    asyncio.run(main())
