"""
Admin panel — FastAPI + Jinja2 + Bootstrap 5 dark theme.
Runs on port 8080 alongside the Telegram bot.
"""

import math
from datetime import datetime, timedelta

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import ADMIN_PANEL_PASS, ADMIN_PANEL_USER, TARIFFS
from database.models import (
    Announcement, AnnouncementGroup, PaymentRequest,
    TelegramAccount, User,
)

templates = Jinja2Templates(directory="admin/templates")
_signer: URLSafeTimedSerializer = None
_factory: async_sessionmaker = None


def create_admin_app(session_factory: async_sessionmaker) -> FastAPI:
    global _factory, _signer
    _factory = session_factory
    _signer = URLSafeTimedSerializer("elon-admin-secret-2025")

    app = FastAPI(docs_url=None, redoc_url=None)

    # ── Auth helpers ──────────────────────────────────────────

    def make_cookie(response, value: str):
        token = _signer.dumps(value)
        response.set_cookie("admin_token", token, httponly=True, max_age=86400 * 7)

    def check_auth(request: Request) -> bool:
        token = request.cookies.get("admin_token")
        if not token:
            return False
        try:
            _signer.loads(token, max_age=86400 * 7)
            return True
        except Exception:
            return False

    def require_auth(request: Request):
        if not check_auth(request):
            raise RedirectResponse("/admin/login", status_code=302)

    # ── Routes ───────────────────────────────────────────────

    @app.get("/admin/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str = ""):
        return templates.TemplateResponse("login.html", {"request": request, "error": error})

    @app.post("/admin/login")
    async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
        if username == ADMIN_PANEL_USER and password == ADMIN_PANEL_PASS:
            resp = RedirectResponse("/admin/", status_code=302)
            make_cookie(resp, username)
            return resp
        return templates.TemplateResponse("login.html", {"request": request, "error": "Noto'g'ri login yoki parol"})

    @app.get("/admin/logout")
    async def logout():
        resp = RedirectResponse("/admin/login", status_code=302)
        resp.delete_cookie("admin_token")
        return resp

    @app.get("/admin/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)
        async with _factory() as session:
            total_users = (await session.scalar(select(func.count(User.id)))) or 0
            premium = (await session.scalar(
                select(func.count(User.id)).where(User.is_premium == True)
            )) or 0
            now = datetime.utcnow()
            trial_active = (await session.scalar(
                select(func.count(User.id)).where(
                    User.is_premium == False,
                    User.trial_expires_at > now,
                )
            )) or 0
            total_ann = (await session.scalar(select(func.count(Announcement.id)))) or 0
            pending_pay = (await session.scalar(
                select(func.count(PaymentRequest.id)).where(PaymentRequest.status == "pending")
            )) or 0

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "total_users": total_users,
            "premium": premium,
            "trial_active": trial_active,
            "total_ann": total_ann,
            "pending_pay": pending_pay,
        })

    @app.get("/admin/users", response_class=HTMLResponse)
    async def users_list(
        request: Request,
        q: str = "",
        page: int = 1,
        per_page: int = 15,
    ):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)

        async with _factory() as session:
            stmt = select(User).order_by(User.created_at.desc())
            if q:
                stmt = stmt.where(
                    User.full_name.ilike(f"%{q}%") |
                    User.phone.ilike(f"%{q}%") |
                    User.username.ilike(f"%{q}%")
                )

            total = (await session.scalar(
                select(func.count()).select_from(stmt.subquery())
            )) or 0
            users = list(await session.scalars(
                stmt.offset((page - 1) * per_page).limit(per_page)
            ))

            # Enrich with account + announcement count
            enriched = []
            now = datetime.utcnow()
            for u in users:
                acc_count = (await session.scalar(
                    select(func.count(TelegramAccount.id)).where(
                        TelegramAccount.user_id == u.id,
                        TelegramAccount.is_active == True,
                    )
                )) or 0
                ann_count = (await session.scalar(
                    select(func.count(Announcement.id)).where(Announcement.user_id == u.id)
                )) or 0

                if u.is_premium:
                    status = "premium"
                elif u.trial_expires_at and u.trial_expires_at > now:
                    status = "trial"
                else:
                    status = "expired"

                enriched.append({
                    "id": u.id,
                    "telegram_id": u.telegram_id,
                    "full_name": u.full_name or "—",
                    "phone": u.phone or "—",
                    "username": f"@{u.username}" if u.username else "—",
                    "is_premium": u.is_premium,
                    "status": status,
                    "trial_expires_at": u.trial_expires_at,
                    "created_at": u.created_at,
                    "acc_count": acc_count,
                    "ann_count": ann_count,
                })

        return templates.TemplateResponse("users.html", {
            "request": request,
            "users": enriched,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, math.ceil(total / per_page)),
            "q": q,
        })

    @app.post("/admin/users/{user_id}/activate")
    async def activate_user(request: Request, user_id: int, days: int = Form(30)):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)
        async with _factory() as session:
            user = await session.get(User, user_id)
            if user:
                user.is_premium = True
                base = max(user.trial_expires_at or datetime.utcnow(), datetime.utcnow())
                user.trial_expires_at = base + timedelta(days=days)
                await session.commit()
        return RedirectResponse("/admin/users", status_code=302)

    @app.post("/admin/users/{user_id}/deactivate")
    async def deactivate_user(request: Request, user_id: int):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)
        async with _factory() as session:
            user = await session.get(User, user_id)
            if user:
                user.is_premium = False
                user.trial_expires_at = datetime.utcnow()
                await session.commit()
        return RedirectResponse("/admin/users", status_code=302)

    @app.get("/admin/payments", response_class=HTMLResponse)
    async def payments_list(request: Request, status: str = "all", page: int = 1):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)

        per_page = 15
        async with _factory() as session:
            stmt = select(PaymentRequest).order_by(PaymentRequest.created_at.desc())
            if status != "all":
                stmt = stmt.where(PaymentRequest.status == status)

            total = (await session.scalar(
                select(func.count()).select_from(stmt.subquery())
            )) or 0
            payments = list(await session.scalars(
                stmt.offset((page - 1) * per_page).limit(per_page)
            ))

            enriched = []
            for p in payments:
                user = await session.get(User, p.user_id)
                enriched.append({
                    "id": p.id,
                    "user": user,
                    "tariff_name": p.tariff_name or "—",
                    "amount": p.amount,
                    "status": p.status,
                    "receipt_file_id": p.receipt_file_id,
                    "created_at": p.created_at,
                    "processed_at": p.processed_at,
                })

        return templates.TemplateResponse("payments.html", {
            "request": request,
            "payments": enriched,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, math.ceil(total / per_page)),
            "status_filter": status,
        })

    @app.post("/admin/payments/{pay_id}/approve")
    async def approve_payment(request: Request, pay_id: int, days: int = Form(30)):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)
        async with _factory() as session:
            pr = await session.get(PaymentRequest, pay_id)
            if pr:
                pr.status = "approved"
                pr.processed_at = datetime.utcnow()
                user = await session.get(User, pr.user_id)
                if user:
                    user.is_premium = True
                    base = max(user.trial_expires_at or datetime.utcnow(), datetime.utcnow())
                    user.trial_expires_at = base + timedelta(days=days)
                await session.commit()
        return RedirectResponse("/admin/payments", status_code=302)

    @app.post("/admin/payments/{pay_id}/reject")
    async def reject_payment(request: Request, pay_id: int):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)
        async with _factory() as session:
            pr = await session.get(PaymentRequest, pay_id)
            if pr:
                pr.status = "rejected"
                pr.processed_at = datetime.utcnow()
                await session.commit()
        return RedirectResponse("/admin/payments", status_code=302)

    @app.get("/admin/announcements", response_class=HTMLResponse)
    async def announcements_list(request: Request, page: int = 1):
        if not check_auth(request):
            return RedirectResponse("/admin/login", status_code=302)

        per_page = 15
        async with _factory() as session:
            total = (await session.scalar(select(func.count(Announcement.id)))) or 0
            anns = list(await session.scalars(
                select(Announcement)
                .order_by(Announcement.created_at.desc())
                .offset((page - 1) * per_page).limit(per_page)
            ))
            enriched = []
            for a in anns:
                user = await session.get(User, a.user_id)
                acc = await session.get(TelegramAccount, a.account_id) if a.account_id else None
                grp_count = (await session.scalar(
                    select(func.count(AnnouncementGroup.id))
                    .where(AnnouncementGroup.announcement_id == a.id)
                )) or 0
                enriched.append({
                    "id": a.id,
                    "user": user,
                    "phone": acc.phone if acc else "—",
                    "text": a.text[:80] + ("..." if len(a.text) > 80 else ""),
                    "message_type": a.message_type.value,
                    "interval": a.interval_minutes,
                    "status": a.status.value,
                    "is_active": a.is_active,
                    "group_count": grp_count,
                    "last_sent": a.last_sent_at,
                    "created_at": a.created_at,
                })

        return templates.TemplateResponse("announcements.html", {
            "request": request,
            "announcements": enriched,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, math.ceil(total / per_page)),
        })

    # Redirect root to admin
    @app.get("/")
    async def root():
        return RedirectResponse("/admin/", status_code=302)

    return app
