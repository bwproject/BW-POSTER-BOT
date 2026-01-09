import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, GROUPS
from db import init_db, save_message, get_message
from scheduler import scheduler


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =======================
# /start
# =======================
@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Пришли мне любое сообщение.\n"
        "Я предложу куда и когда его запостить."
    )


# =======================
# Принимаем ЛЮБОЕ сообщение
# =======================
@dp.message()
async def catch_message(message: Message):
    post_id = await save_message(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=message.message_id
    )

    kb = InlineKeyboardBuilder()
    for group_name in GROUPS.keys():
        kb.add(
            InlineKeyboardButton(
                text=f"📢 {group_name}",
                callback_data=f"group:{post_id}:{group_name}"
            )
        )

    kb.adjust(1)

    await message.answer(
        "Выбери группу для постинга:",
        reply_markup=kb.as_markup()
    )


# =======================
# Выбор группы
# =======================
@dp.callback_query(F.data.startswith("group:"))
async def group_choose(callback: CallbackQuery):
    _, post_id, group_name = callback.data.split(":")

    kb = InlineKeyboardBuilder()
    kb.add(
        InlineKeyboardButton(
            text="🚀 Сейчас",
            callback_data=f"now:{post_id}:{group_name}"
        ),
        InlineKeyboardButton(
            text="⏰ Через 1 час",
            callback_data=f"later:{post_id}:{group_name}:3600"
        )
    )

    await callback.message.edit_text(
        f"Когда постить в «{group_name}»?",
        reply_markup=kb.as_markup()
    )


# =======================
# Постим сразу
# =======================
@dp.callback_query(F.data.startswith("now:"))
async def post_now(callback: CallbackQuery):
    _, post_id, group_name = callback.data.split(":")

    chat_id, message_id = await get_message(int(post_id))

    await bot.copy_message(
        chat_id=GROUPS[group_name],
        from_chat_id=chat_id,
        message_id=message_id
    )

    await callback.message.edit_text("✅ Сообщение опубликовано")


# =======================
# Отложенный пост
# =======================
@dp.callback_query(F.data.startswith("later:"))
async def post_later(callback: CallbackQuery):
    _, post_id, group_name, delay = callback.data.split(":")

    chat_id, message_id = await get_message(int(post_id))

    scheduler.add_job(
        bot.copy_message,
        trigger="date",
        run_date=None,
        seconds=int(delay),
        kwargs={
            "chat_id": GROUPS[group_name],
            "from_chat_id": chat_id,
            "message_id": message_id
        }
    )

    await callback.message.edit_text("⏳ Сообщение запланировано")


# =======================
# Запуск
# =======================
async def main():
    await init_db()
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
