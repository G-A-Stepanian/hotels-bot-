from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

router = Router()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню — кнопки запуска поиска."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💸 Дешёвые", callback_data="cmd:lowprice"),
                InlineKeyboardButton(text="💎 Дорогие", callback_data="cmd:highprice"),
            ],
            [
                InlineKeyboardButton(
                    text="⚖️ По диапазону", callback_data="cmd:bestdeal"
                ),
            ],
            [
                InlineKeyboardButton(text="🕓 История", callback_data="cmd:history"),
            ],
        ]
    )


START_TEXT = (
    "👋 <b>Добро пожаловать в HotelSearchBot!</b>\n\n"
    "Я помогу найти отели через Booking API.\n"
    "Выберите тип поиска:"
)

HELP_TEXT = (
    "ℹ️ <b>Доступные команды:</b>\n\n"
    "💸 /lowprice — самые дешёвые отели\n"
    "💎 /highprice — самые дорогие отели\n"
    "⚖️ /bestdeal — отели в диапазоне цены\n"
    "🕓 /history — история поиска\n"
    "❌ /cancel — отменить текущий поиск\n\n"
    "Или нажмите кнопку ниже:"
)


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    """Приветствие и главное меню."""
    await state.clear()
    await message.answer(
        START_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    """Справка с кнопками быстрого запуска."""
    await message.answer(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(lambda c: c.data is not None and c.data.startswith("cmd:"))
async def menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обрабатывает нажатие кнопок главного меню."""
    # ИСПРАВЛЕНИЕ start.py:75 — callback.data гарантированно str (проверили выше)
    command = callback.data.split(":")[1]  # type: ignore[union-attr]

    if not isinstance(callback.message, Message):
        # ИСПРАВЛЕНИЕ start.py:81 — InaccessibleMessage не имеет .delete()
        await callback.answer()
        return

    await callback.message.delete()

    if command == "history":
        # ИСПРАВЛЕНИЕ start.py:88 — правильное имя функции history_handler
        from handlers.history import history_handler

        await history_handler(callback.message, state)
    else:
        from handlers.search import start_search

        # ИСПРАВЛЕНИЕ start.py:94 — callback.message гарантированно Message (проверили выше)
        await start_search(callback.message, state, command)

    await callback.answer()
