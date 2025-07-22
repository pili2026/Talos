import asyncio

from dotenv import load_dotenv

from device_manager import AsyncDeviceManager
from device_monitor import AsyncDeviceMonitor
from util.logger_config import setup_logging
from util.notifier.email_notifier import EmailNotifier
from util.pubsub.in_memory_pubsub import InMemoryPubSub


async def main():
    setup_logging(log_to_file=True)
    load_dotenv()

    pubsub = InMemoryPubSub()
    async_device_manager = AsyncDeviceManager()
    await async_device_manager.init()

    monitor = AsyncDeviceMonitor(async_device_manager, pubsub)
    email_notifier = EmailNotifier(pubsub)

    await asyncio.gather(monitor.run(), email_notifier.run())


if __name__ == "__main__":
    asyncio.run(main())
