import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.version import __version__

logger = logging.getLogger("glafira")
router = Router()


MENU_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="👔 Глафира — рекрутёр", callback_data="recruit:menu")],
])


HELLO_TEXT = (
    f"👔 <b>Глафира-РекрутерЕвромед</b> <i>v{__version__}</i>\n\n"
    "AI-рекрутёр. Оцениваю кандидатов в Talantix:\n"
    "  • сравниваю резюме с описанием вакансии через Claude\n"
    "  • ставлю балл 0–100\n"
    "  • публикую комментарий с разбивкой по критериям\n"
    "  • добавляю префикс с баллом к фамилии для сортировки\n\n"
    "Жми кнопку, чтобы загрузить список вакансий."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(HELLO_TEXT, reply_markup=MENU_KB)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELLO_TEXT, reply_markup=MENU_KB)


@router.callback_query(F.data == "back:menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(HELLO_TEXT, reply_markup=MENU_KB)
    await callback.answer()
