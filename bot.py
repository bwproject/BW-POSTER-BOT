import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.text import Text

from config import BOT_TOKEN, GROUPS, ADMINS
from db import init_db, save_message, get_message, update_caption
from scheduler import scheduler

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =======================
# /start
# =======================
@dp.message(CommandStart())
async def start_handler(msg: Message):
    await msg.answer(
        "Привет! Отправь мне сообщение, а я предложу куда и когда его запостить."
    )


# =======================
# Проверка доступа
# =======================
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# =======================
# Ловим любое сообщение
# =======================
@dp.message()
async def catch_message(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.reply("❌ У тебя нет доступа к постингу.")
        return

    post_id = await save_message(msg.from_user.id, msg.chat.id, msg.message_id, msg.text)

    kb = InlineKeyboardBuilder()
    for name in GROUPS.keys():
        kb.add(InlineKeyboardButton(text=f"📢 {name}", callback_data=f"group:{post_id}:{name}"))
    kb.adjust(1)

    await msg.answer("Выбери группу для постинга:", reply_markup=kb.as_markup())


# =======================
# Выбор группы
# =======================
@dp.callback_query(F.data.startswith("group:"))
async def group_choose(cb: CallbackQuery):
    _, post_id, group_name = cb.data.split(":")

    kb = InlineKeyboardBuilder()
    kb.add(
        InlineKeyboardButton(text="🚀 Сейчас", callback_data=f"now:{post_id}:{group_name}"),
        InlineKeyboardButton(text="⏰ По времени", callback_data=f"manual:{post_id}:{group_name}")
    )

    await cb.message.edit_text(f"Когда постить в «{group_name}»?", reply_markup=kb.as_markup())


# =======================
# Немедленный пост
# =======================
@dp.callback_query(F.data.startswith("now:"))
async def post_now(cb: CallbackQuery):
    _, post_id, group_name = cb.data.split(":")
    chat_id, message_id, caption = await get_message(int(post_id))

    await bot.copy_message(chat_id=GROUPS[group_name], from_chat_id=chat_id, message_id=message_id)
    await cb.message.edit_text("✅ Сообщение опубликовано")


# =======================
# Ввод времени вручную
# =======================
@dp.callback_query(F.data.startswith("manual:"))
async def post_manual(cb: CallbackQuery):
    _, post_id, group_name = cb.data.split(":")
    await cb.message.edit_text(
        "📅 Введи дату и время в формате YYYY-MM-DD HH:MM (например, 2026-01-09 18:30)"
    )

    dp.register_message_handler(
        lambda msg: manual_time_handler(msg, post_id, group_name),
        F.from_user.id == cb.from_user.id,
        state=None
    )


async def manual_time_handler(msg: Message, post_id, group_name):
    try:
        dt = datetime.strptime(msg.text, "%Y-%m-%d %H:%M")
    except ValueError:
        await msg.reply("❌ Неверный формат. Попробуй ещё раз.")
        return

    # редактирование текста перед постом
    await msg.answer("✏️ Если хочешь изменить текст перед постом, отправь новый текст. Иначе пришли '.'")
    dp.register_message_handler(
        lambda m: edit_caption_handler(m, post_id, group_name, dt),
        F.from_user.id == msg.from_user.id,
        state=None
    )


async def edit_caption_handler(msg: Message, post_id, group_name, dt: datetime):
    if msg.text != ".":
        await update_caption(post_id, msg.text)
    chat_id, message_id, caption = await get_message(int(post_id))

    scheduler.add_job(
        bot.copy_message,
        trigger="date",
        run_date=dt,
        kwargs={
            "chat_id": GROUPS[group_name],
            "from_chat_id": chat_id,
            "message_id": message_id
        }
    )

    await msg.answer(f"⏳ Сообщение запланировано на {dt.strftime('%Y-%m-%d %H:%M')}")


# =======================
# Запуск
# =======================
async def main():
    await init_db()
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
