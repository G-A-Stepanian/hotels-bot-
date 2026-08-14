"""
/cancel — отмена текущего FSM-сценария.

Очищает состояние пользователя, чтобы можно было начать поиск заново.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router(name=__name__)


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext) -> None:
    """
    Отменить активный сценарий (если он есть) и очистить FSM state.
    """
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.")
        return

    await state.clear()
    await message.answer(
        "Ок, отменено. Можешь начать заново: /lowprice, /highprice или /bestdeal."
    )
