"""
Verify Telegram bot configuration and access
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

import asyncio
import os

import httpx
from dotenv import load_dotenv

# Load environment variables
env_path = project_root / ".env"
load_dotenv(env_path)

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip('"')


async def check_bot():
    print("=" * 60)
    print("Telegram Bot Verification")
    print("=" * 60)
    print(f"Bot Token: {bot_token[:20] if bot_token else 'NOT SET'}...")
    print(f"Chat ID: {chat_id if chat_id else 'NOT SET'}")
    print("=" * 60)

    if not bot_token:
        print("TELEGRAM_BOT_TOKEN not set in .env")
        return

    if not chat_id:
        print("TELEGRAM_CHAT_ID not set in .env")
        return

    # Check bot info
    print("\nChecking bot info...")
    url = f"https://api.telegram.org/bot{bot_token}/getMe"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            result = response.json()

            if result.get("ok"):
                bot_info = result["result"]
                print(f"Bot found!")
                print(f"   Username: @{bot_info.get('username')}")
                print(f"   Name: {bot_info.get('first_name')}")
            else:
                print(f"Bot error: {result.get('description')}")
                return
        except Exception as e:
            print(f"Connection error: {e}")
            return

    # Check chat access
    print(f"\nChecking chat access (ID: {chat_id})...")
    url = f"https://api.telegram.org/bot{bot_token}/getChat"
    params = {"chat_id": chat_id}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            result = response.json()

            if result.get("ok"):
                chat_info = result["result"]
                print(f"Chat found!")
                print(f"   Type: {chat_info.get('type')}")
                print(f"   Title: {chat_info.get('title', 'N/A')}")
                if chat_info.get("type") in ["group", "supergroup"]:
                    print(f"   Members: ~{chat_info.get('member_count', 'Unknown')}")
            else:
                error_code = result.get("error_code")
                description = result.get("description")
                print(f"Chat error ({error_code}): {description}")

                if error_code == 400:
                    print("\nSolution:")
                    print("   1. Make sure the bot is added to the group")
                    print("   2. Send a message in the group")
                    print("   3. Try again")
                elif error_code == 403:
                    print("\nSolution:")
                    print("   1. Re-add the bot to the group")
                    print("   2. Make sure bot is not blocked")
                return
        except Exception as e:
            print(f"Connection error: {e}")
            return

    print("=" * 60)
    print("Verification complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(check_bot())
