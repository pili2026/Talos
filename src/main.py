import asyncio
import logging

from device_manager import AsyncDeviceManager
from device_monitor import DeviceMonitor
from util.notifier.email_notifier import EmailNotifier
from util.pubsub.in_memory_pubsub import InMemoryPubSub


async def main():
    logging.basicConfig(level=logging.INFO)

    pubsub = InMemoryPubSub()
    async_device_manager = AsyncDeviceManager()
    await async_device_manager.init()

    monitor = DeviceMonitor(async_device_manager, pubsub)
    email_notifier = EmailNotifier(pubsub)

    await asyncio.gather(monitor.run(), email_notifier.run())


if __name__ == "__main__":
    asyncio.run(main())
