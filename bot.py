import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode, ContentType

from config import BOT_TOKEN, GROUPS, ADMINS, POST_FOOTER
from db import init_db, save_message, get_message
from scheduler import scheduler, start_scheduler
from logger import setup_logger


# ==================================================
# LOGGING
# ==================================================
setup_logger()
log = logging.getLogger("BOT")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


# ==================================================
# HELPERS
# ==================================================
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def build_footer(text: Optional[str]) -> str:
    if text:
        return f"{text.strip()}\n\n{POST_FOOTER.strip()}"
    return POST_FOOTER.strip()


def split_text(text: str, limit: int) -> Tuple[str, Optional[str]]:
    if len(text) <= limit:
        return text, None
    return text[:limit], text[limit:]


# ==================================================
# SENDER (ВЕСЬ СМАРТ ЗДЕСЬ)
# ==================================================
async def smart_send(
    target_chat: int,
    source_chat: int,
    message_id: int,
    original_text: Optional[str],
    content_type: str
):
    footer_text = build_footer(original_text)

    # -----------------------------
    # 📝 TEXT
    # -----------------------------
    if content_type == ContentType.TEXT:
        first, second = split_text(footer_text, TEXT_LIMIT)
        await bot.send_message(target_chat, first, parse_mode=ParseMode.HTML)
        log.info("Текстовый пост отправлен")

        if second:
            await bot.send_message(target_chat, second, parse_mode=ParseMode.HTML)
            log.info("Отправлено продолжение текста")
        return

    # -----------------------------
    # 🎤 VOICE / 🎥 VIDEO_NOTE
    # -----------------------------
    if content_type in (ContentType.VOICE, ContentType.VIDEO_NOTE):
        await bot.copy_message(
            chat_id=target_chat,
            from_chat_id=source_chat,
            message_id=message_id
        )
        await bot.send_message(
            chat_id=target_chat,
            text=footer_text,
            parse_mode=ParseMode.HTML
        )
        log.info("Голос/кружок + подпись вторым сообщением")
        return

    # -----------------------------
    # 🖼 MEDIA WITH CAPTION
    # -----------------------------
    first, second = split_text(footer_text, CAPTION_LIMIT)

    await bot.copy_message(
        chat_id=target_chat,
        from_chat_id=source_chat,
        message_id=message_id,
        caption=first,
        parse_mode=ParseMode.HTML
    )

    log.info("Медиа пост отправлен")

    if second:
        await bot.send_message(
            chat_id=target_chat,
            text=second,
            parse_mode=ParseMode.HTML
        )
        log.info("Отправлено продолжение caption")


# ==================================================
# /start
# ==================================================
@dp.message(CommandStart())
async def start_handler(msg: Message):
    log.info(f"/start user_id={msg.from_user.id}")
    await msg.answer("Отправь сообщение для постинга")


# ==================================================
# CATCH MESSAGE
# ==================================================
@dp.message()
async def catch_message(msg: Message):
    if not is_admin(msg.from_user.id):
        log.warning(f"ACCESS DENIED user_id={msg.from_user.id}")
        await msg.reply("❌ Нет доступа")
        return

    log.info(
        f"Получено сообщение "
        f"type={msg.content_type} "
        f"user_id={msg.from_user.id}"
    )

    post_id = await save_message(
        msg.from_user.id,
        msg.chat.id,
        msg.message_id,
        msg.text or msg.caption
    )

    kb = InlineKeyboardBuilder()
    for g in GROUPS:
        kb.add(InlineKeyboardButton(
            text=f"📢 {g}",
            callback_data=f"group:{post_id}:{g}"
        ))
    kb.adjust(1)

    await msg.answer("Куда постить?", reply_markup=kb.as_markup())


# ==================================================
# GROUP SELECT
# ==================================================
@dp.callback_query(F.data.startswith("group:"))
async def choose_group(cb: CallbackQuery):
    _, post_id, group = cb.data.split(":")
    log.info(f"Группа выбрана post_id={post_id} group={group}")

    kb = InlineKeyboardBuilder()
    kb.add(
        InlineKeyboardButton(text="🚀 Сейчас", callback_data=f"now:{post_id}:{group}"),
        InlineKeyboardButton(text="⏰ По времени", callback_data=f"time:{post_id}:{group}")
    )

    await cb.message.edit_text("Когда постить?", reply_markup=kb.as_markup())


# ==================================================
# POST NOW
# ==================================================
@dp.callback_query(F.data.startswith("now:"))
async def post_now(cb: CallbackQuery):
    _, post_id, group = cb.data.split(":")
    chat_id, msg_id, text = await get_message(int(post_id))

    await smart_send(
        target_chat=GROUPS[group],
        source_chat=chat_id,
        message_id=msg_id,
        original_text=text,
        content_type=cb.message.reply_to_message.content_type
    )

    log.info(f"ПОСТ ОТПРАВЛЕН post_id={post_id}")
    await cb.message.edit_text("✅ Опубликовано")


# ==================================================
# SCHEDULE
# ==================================================
@dp.callback_query(F.data.startswith("time:"))
async def ask_time(cb: CallbackQuery):
    _, post_id, group = cb.data.split(":")
    await cb.message.edit_text("Введите дату и время:\nYYYY-MM-DD HH:MM")

    dp.register_message_handler(
        lambda m: schedule_post(m, post_id, group),
        F.from_user.id == cb.from_user.id
    )


async def schedule_post(msg: Message, post_id: str, group: str):
    try:
        dt = datetime.strptime(msg.text, "%Y-%m-%d %H:%M")
    except ValueError:
        await msg.reply("❌ Неверный формат")
        return

    chat_id, msg_id, text = await get_message(int(post_id))

    scheduler.add_job(
        smart_send,
        trigger="date",
        run_date=dt,
        kwargs={
            "target_chat": GROUPS[group],
            "source_chat": chat_id,
            "message_id": msg_id,
            "original_text": text,
            "content_type": msg.content_type
        }
    )

    log.info(f"ПОСТ ЗАПЛАНИРОВАН post_id={post_id} time={dt}")
    await msg.answer(f"⏳ Запланировано на {dt}")


# ==================================================
# START
# ==================================================
async def main():
    log.info("=== BOT STARTED ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
