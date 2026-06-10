import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_PANEL_PORT
from database.db import async_session_factory, init_db
from bot.router import main_router
from bot.middlewares.db import DbMiddleware
from scheduler import run_scheduler
from admin.app import create_admin_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Initialising database...")
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbMiddleware(async_session_factory))
    dp.include_router(main_router)

    # Admin panel (FastAPI on port 8080)
    admin_app = create_admin_app(async_session_factory)
    config = uvicorn.Config(
        admin_app,
        host="0.0.0.0",
        port=ADMIN_PANEL_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    logger.info("Bot + Admin panel starting...")
    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        server.serve(),
        run_scheduler(async_session_factory, bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
