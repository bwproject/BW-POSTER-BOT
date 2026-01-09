#bot.py https://github.com/bwproject/BW-POSTER-BOT/edit/main/bot.py

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from config import BOT_TOKEN, GROUPS, POST_FOOTER, MAX_TEXT
from db import (
    init_db, save_message, get_post, get_history, update_text,
    set_status, set_job, get_drafts, set_target_chat, update_file_path
)
from scheduler import scheduler, start_scheduler

TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# ─── ЛОГИ ─────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("BOT")

# ─── FSM ──────────────────────────────
class EditPost(StatesGroup):
    waiting_text = State()

# ─── BOT ──────────────────────────────
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ─── ВСПОМОГАТЕЛЬНО ──────────────────
def group_keyboard(post_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Mes", callback_data=f"group:{post_id}:The_Mr_Mes109"),
            InlineKeyboardButton(text="BW", callback_data=f"group:{post_id}:ProjectBW"),
            InlineKeyboardButton(text="Помойка", callback_data=f"group:{post_id}:Trash")
        ],
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit:{post_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel:{post_id}")
        ]
    ])

def schedule_keyboard(post_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сейчас", callback_data=f"schedule:{post_id}:0"),
            InlineKeyboardButton(text="+5 мин", callback_data=f"schedule:{post_id}:5"),
            InlineKeyboardButton(text="+10 мин", callback_data=f"schedule:{post_id}:10")
        ],
        [
            InlineKeyboardButton(text="+20 мин", callback_data=f"schedule:{post_id}:20"),
            InlineKeyboardButton(text="+30 мин", callback_data=f"schedule:{post_id}:30"),
            InlineKeyboardButton(text="+60 мин", callback_data=f"schedule:{post_id}:60")
        ],
        [
            InlineKeyboardButton(text="Выбрать дату/время", callback_data=f"schedule_custom:{post_id}")
        ]
    ])

# ─── ЗАГРУЗКА МЕДИА ──────────────────
async def download_media(msg: Message):
    file_path = None

    if msg.content_type == ContentType.PHOTO:
        file = msg.photo[-1]  # берём самый большой размер
        file_info = await bot.get_file(file.file_id)
        file_path = os.path.join(TEMP_DIR, f"{file.file_id}.jpg")
        await bot.download(file_info.file_path, destination=file_path)

    elif msg.content_type == ContentType.VIDEO:
        file_info = await bot.get_file(msg.video.file_id)
        file_path = os.path.join(TEMP_DIR, f"{msg.video.file_id}.mp4")
        await bot.download(file_info.file_path, destination=file_path)

    return file_path

# ─── START ───────────────────────────
@dp.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="История", callback_data="show_history")],
        [InlineKeyboardButton(text="Черновики", callback_data="show_drafts")]
    ])
    await msg.answer("Пришли пост для публикации", reply_markup=kb)

# ─── ПОЛУЧЕНИЕ ПОСТОВ ───────────────
@dp.message()
async def receive_post(msg: Message):
    log.info(f"Получен пост type={msg.content_type}")
    text = msg.text or msg.caption or ""

    post_id = await save_message(msg.from_user.id, msg.chat.id, msg.message_id, text, msg.content_type)

    file_path = None
    if msg.content_type in [ContentType.PHOTO, ContentType.VIDEO]:
        file_path = await download_media(msg)
        if file_path:
            await update_file_path(post_id, file_path)

    await set_status(post_id, "draft")
    await msg.answer("Выбери действие:", reply_markup=group_keyboard(post_id))

# ─── РЕДАКТИРОВАНИЕ ──────────────────
@dp.callback_query(F.data.startswith("edit:"))
async def edit_post(cb: CallbackQuery, state: FSMContext):
    post_id = int(cb.data.split(":")[1])
    await state.update_data(post_id=post_id)
    await cb.message.answer("✏️ Пришли новый текст")
    await state.set_state(EditPost.waiting_text)
    await cb.answer()

@dp.message(EditPost.waiting_text)
async def save_new_text(msg: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data["post_id"]
    await update_text(post_id, msg.text)
    await set_status(post_id, "draft")
    log.info(f"Текст обновлён post_id={post_id}")
    await state.clear()
    await msg.answer("✅ Текст обновлён")

# ─── ОТМЕНА ─────────────────────────
@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_post(cb: CallbackQuery):
    post_id = int(cb.data.split(":")[1])
    await set_status(post_id, "cancelled")
    log.info(f"Пост отменён post_id={post_id}")
    await cb.message.edit_text("❌ Публикация отменена")
    await cb.answer()

# ─── ВЫБОР ГРУППЫ ───────────────────
@dp.callback_query(F.data.startswith("group:"))
async def choose_group(cb: CallbackQuery):
    _, post_id, group_name = cb.data.split(":")
    target_chat_id = GROUPS.get(group_name)
    if not target_chat_id:
        await cb.message.answer("❌ Ошибка: группа не найдена")
        await cb.answer()
        return
    await set_target_chat(post_id, target_chat_id)
    kb = schedule_keyboard(post_id)
    await cb.message.edit_text(f"Когда публикуем в {group_name}?", reply_markup=kb)
    await cb.answer()

# ─── ПЛАНИРОВАНИЕ ───────────────────
@dp.callback_query(F.data.startswith("schedule:"))
async def schedule_post(cb: CallbackQuery):
    _, post_id, minutes = cb.data.split(":")
    post_id, minutes = int(post_id), int(minutes)
    run_at = datetime.now() + timedelta(minutes=minutes)
    await set_status(post_id, "scheduled")
    job_id = str(uuid.uuid4())
    scheduler.add_job(
        publish,
        trigger="date",
        run_date=run_at,
        args=(post_id,),
        id=job_id
    )
    await set_job(post_id, job_id)
    await cb.message.edit_text(f"⏰ Пост запланирован через {minutes} мин")
    await cb.answer()

# ─── ПУБЛИКАЦИЯ ─────────────────────
async def publish(post_id):
    post = await get_post(post_id)
    if post["status"] == "cancelled":
        return

    target_chat_id = post["target_chat_id"] or post["chat_id"]
    text = post["caption"] or ""

    # Сообщение об успешной отправке автору
    await bot.send_message(post["chat_id"], "✅ Пост успешно отправлен")

    # Отправка контента
    if post["content_type"] == ContentType.TEXT:
        await bot.send_message(target_chat_id, text)

    elif post["content_type"] in [ContentType.PHOTO, ContentType.VIDEO]:
        if post.get("file_path") and os.path.exists(post["file_path"]):
            if post["content_type"] == ContentType.PHOTO:
                await bot.send_photo(target_chat_id, photo=open(post["file_path"], "rb"), caption=text)
            elif post["content_type"] == ContentType.VIDEO:
                await bot.send_video(target_chat_id, video=open(post["file_path"], "rb"), caption=text)
        else:
            log.warning(f"Файл для post_id={post_id} не найден, отправляем текст")
            await bot.send_message(target_chat_id, text)

    elif post["content_type"] in [ContentType.VOICE, ContentType.ANIMATION, ContentType.DOCUMENT]:
        await bot.forward_message(target_chat_id, from_chat_id=post["chat_id"], message_id=post["message_id"])

    await set_status(post_id, "posted")
    log.info(f"ПОСТ ОТПРАВЛЕН post_id={post_id} в чат {target_chat_id}")

# ─── MAIN ───────────────────────────
async def main():
    log.info("=== BOT STARTED ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
