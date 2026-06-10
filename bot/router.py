from aiogram import Router

from bot.handlers import start, account, announcement, my_announcements, subscriptions, admin_panel

main_router = Router()
main_router.include_router(admin_panel.router)   # admin first so /admin doesn't get swallowed
main_router.include_router(start.router)
main_router.include_router(account.router)
main_router.include_router(announcement.router)
main_router.include_router(my_announcements.router)
main_router.include_router(subscriptions.router)
