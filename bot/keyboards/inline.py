from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ---------------------------------------------------------------------------
# Group selection
# ---------------------------------------------------------------------------

def groups_keyboard(groups: list[dict], selected: list[str]) -> InlineKeyboardMarkup:
    """
    Each group on its own row with ✅/❌ prefix.
    Bottom row: "Barchasini tanlash" (0 selected) OR "✅ Tasdiqlash (N ta)" + "🔙 Orqaga"
    """
    builder = InlineKeyboardBuilder()
    sel = set(selected)

    for g in groups:
        gid = str(g["id"])
        mark = "✅" if gid in sel else "❌"
        builder.button(text=f"{mark} {g['title'][:38]}", callback_data=f"grp:t:{gid}")

    if sel:
        builder.button(text=f"✅ Tasdiqlash ({len(sel)} ta)", callback_data="grp:confirm")
    else:
        builder.button(text="☑️ Barchasini tanlash", callback_data="grp:all")

    builder.button(text="🔙 Orqaga", callback_data="grp:back")

    total = len(groups)
    # each group → 1 col, then 2 action buttons → 1 col each
    builder.adjust(*([1] * total), 1, 1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Interval selection
# ---------------------------------------------------------------------------

INTERVAL_OPTIONS = [
    (5,    "5 daqiqa"),
    (10,   "10 daqiqa"),
    (15,   "15 daqiqa"),
    (30,   "30 daqiqa"),
    (60,   "1 soat"),
    (180,  "3 soat"),
    (360,  "6 soat"),
    (720,  "12 soat"),
    (1440, "24 soat"),
]


def interval_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes, label in INTERVAL_OPTIONS:
        builder.button(text=label, callback_data=f"int:{minutes}")
    builder.button(text="🔙 Orqaga", callback_data="int:back")
    builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def interval_label(minutes: int) -> str:
    for m, label in INTERVAL_OPTIONS:
        if m == minutes:
            return label
    return f"{minutes} daqiqa"


# ---------------------------------------------------------------------------
# Announcement card (in "Mening xabarlari")
# ---------------------------------------------------------------------------

def announcement_card_kb(ann_id: int, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.button(text="⏸ To'xtatish", callback_data=f"ann:stop:{ann_id}")
    else:
        builder.button(text="▶️ Davom ettirish", callback_data=f"ann:resume:{ann_id}")
    builder.button(text="🗑 O'chirish",           callback_data=f"ann:del:{ann_id}")
    builder.button(text="✏️ Matnni o'zgartirish", callback_data=f"ann:edit:{ann_id}")
    builder.button(text="🔙 Orqaga",              callback_data="ann:back")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Subscriptions / tariff
# ---------------------------------------------------------------------------

def subscription_kb(has_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Obunani uzaytirish",  callback_data="sub:extend")
    builder.button(text="📋 Tarifni o'zgartirish", callback_data="sub:change")
    builder.button(text="🔙 Orqaga",               callback_data="sub:back")
    builder.adjust(1)
    return builder.as_markup()


def tariff_kb(tariffs: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, (name, price, _days) in tariffs.items():
        builder.button(
            text=f"{name} — {price:,} so'm".replace(",", " "),
            callback_data=f"tariff:{key}",
        )
    builder.button(text="🔙 Orqaga", callback_data="tariff:back")
    builder.adjust(1)
    return builder.as_markup()


def cancel_payment_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Bekor qilish", callback_data="pay:cancel")
    builder.adjust(1)
    return builder.as_markup()
