import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, GROUPS, ADMINS
from db import init_db, save_message, get_message, update_caption
from scheduler import scheduler, start_scheduler
from logger import setup_logger

# =======================
# ЛОГГЕР
# =======================
logger = setup_logger()
log = logging.getLogger("BOT")

# =======================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =======================
@dp.message(CommandStart())
async def start_handler(msg: Message):
    log.info(f"/start от user_id={msg.from_user.id}")
    await msg.answer("Отправь сообщение для постинга")


# =======================
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# =======================
@dp.message()
async def catch_message(msg: Message):
    if not is_admin(msg.from_user.id):
        log.warning(f"Отказ доступа user_id={msg.from_user.id}")
        await msg.reply("❌ Нет доступа")
        return

    log.info(
        f"Получено сообщение "
        f"type={msg.content_type} "
        f"user_id={msg.from_user.id} "
        f"message_id={msg.message_id}"
    )

    post_id = await save_message(
        msg.from_user.id,
        msg.chat.id,
        msg.message_id,
        msg.text
    )

    kb = InlineKeyboardBuilder()
    for name in GROUPS:
        kb.add(
            InlineKeyboardButton(
                text=f"📢 {name}",
                callback_data=f"group:{post_id}:{name}"
            )
        )
    kb.adjust(1)

    await msg.answer("Куда постить?", reply_markup=kb.as_markup())


# =======================
@dp.callback_query(F.data.startswith("group:"))
async def group_choose(cb: CallbackQuery):
    _, post_id, group_name = cb.data.split(":")
    log.info(f"Выбрана группа {group_name} post_id={post_id}")

    kb = InlineKeyboardBuilder()
    kb.add(
        InlineKeyboardButton(text="🚀 Сейчас", callback_data=f"now:{post_id}:{group_name}"),
        InlineKeyboardButton(text="⏰ По времени", callback_data=f"manual:{post_id}:{group_name}")
    )

    await cb.message.edit_text(
        f"Когда постить в «{group_name}»?",
        reply_markup=kb.as_markup()
    )


# =======================
@dp.callback_query(F.data.startswith("now:"))
async def post_now(cb: CallbackQuery):
    _, post_id, group_name = cb.data.split(":")
    chat_id, message_id, _ = await get_message(int(post_id))

    await bot.copy_message(
        chat_id=GROUPS[group_name],
        from_chat_id=chat_id,
        message_id=message_id
    )

    log.info(f"ПОСТ ОТПРАВЛЕН СРАЗУ post_id={post_id} group={group_name}")
    await cb.message.edit_text("✅ Опубликовано")


# =======================
@dp.callback_query(F.data.startswith("manual:"))
async def manual_time(cb: CallbackQuery):
    _, post_id, group_name = cb.data.split(":")
    log.info(f"Запрос времени post_id={post_id}")

    await cb.message.edit_text(
        "Введите дату и время:\nYYYY-MM-DD HH:MM"
    )

    dp.register_message_handler(
        lambda msg: manual_time_handler(msg, post_id, group_name),
        F.from_user.id == cb.from_user.id
    )


async def manual_time_handler(msg: Message, post_id, group_name):
    try:
        dt = datetime.strptime(msg.text, "%Y-%m-%d %H:%M")
    except ValueError:
        await msg.reply("❌ Неверный формат")
        return

    scheduler.add_job(
        bot.copy_message,
        trigger="date",
        run_date=dt,
        kwargs={
            "chat_id": GROUPS[group_name],
            "from_chat_id": msg.chat.id,
            "message_id": (await get_message(int(post_id)))[1]
        }
    )

    log.info(
        f"ПОСТ ЗАПЛАНИРОВАН post_id={post_id} "
        f"group={group_name} time={dt}"
    )

    await msg.answer(f"⏳ Запланировано на {dt}")


# =======================
async def main():
    log.info("=== БОТ ЗАПУСКАЕТСЯ ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
