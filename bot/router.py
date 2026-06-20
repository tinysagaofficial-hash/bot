from aiogram import Router

from bot.handlers import start, account, announcement, my_announcements, subscriptions, admin_panel, fallback

main_router = Router()
main_router.include_router(admin_panel.router)
main_router.include_router(start.router)
main_router.include_router(account.router)
main_router.include_router(announcement.router)
main_router.include_router(my_announcements.router)
main_router.include_router(subscriptions.router)
main_router.include_router(fallback.router)  # must be last — catches anything unhandled
