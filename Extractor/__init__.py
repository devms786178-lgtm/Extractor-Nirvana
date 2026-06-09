import asyncio
import logging
from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN
import os
import sys

# Configure logging
logging.basicConfig(
    format="[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# Initialize event loop
loop = asyncio.get_event_loop()

# Use in_memory=True — no session file saved to disk.
# This avoids FLOOD_WAIT (auth.ImportBotAuthorization) on every Render restart
# because Render's filesystem is ephemeral (resets on each deploy/restart).
# With in_memory, Pyrogram does NOT re-import the bot auth from scratch each time;
# it skips writing/reading session files entirely, preventing repeated auth calls.
try:
    app = Client(
        name="extractor_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        sleep_threshold=120,
        workers=500,
        in_memory=True
    )
except Exception as e:
    logger.error(f"Failed to initialize client: {e}")
    sys.exit(1)

async def info_bot():
    global BOT_ID, BOT_NAME, BOT_USERNAME
    try:
        await app.start()
        getme = await app.get_me()
        BOT_ID = getme.id
        BOT_USERNAME = getme.username
        if getme.last_name:
            BOT_NAME = getme.first_name + " " + getme.last_name
        else:
            BOT_NAME = getme.first_name
        logger.info(f"Bot started: @{BOT_USERNAME}")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        sys.exit(1)

# Run the bot
loop.run_until_complete(info_bot())
