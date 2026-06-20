from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards.reply import main_menu

router = Router()


@router.message()
async def global_fallback(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("❌ Bekor qilindi. Asosiy menyu:", reply_markup=main_menu())
