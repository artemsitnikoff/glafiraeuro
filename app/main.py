"""Entry point: aiogram polling. Запуск: `python -m app.main`."""

import asyncio
import logging

from app.bot.create import create_bot, create_dispatcher
from app.services import talantix_token
from app.services.ai_client import AIClient
from app.services.claude_token import init_token_file
from app.services.talantix_client import TalantixClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("glafira")


async def main():
    init_token_file()
    talantix_token.init_from_env()

    bot = create_bot()
    dp = create_dispatcher()

    talantix = TalantixClient()
    ai_client = AIClient()

    dp["talantix"] = talantix
    dp["ai_client"] = ai_client

    logger.info("Glafira bot polling started")
    try:
        await dp.start_polling(bot)
    finally:
        await ai_client.close()
        await talantix.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
