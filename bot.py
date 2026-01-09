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

from config import BOT_TOKEN, GROUPS, POST_FOOTER, MAX_TEXT, TEMP_DIR
from db import (
    init_db, save_message, get_post, get_history, update_text,
    set_status, set_job, get_drafts, set_target_chat
)
from scheduler import scheduler, start_scheduler

# ─── ЛОГИ ─────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("BOT")

# ─── FSM ──────────────────────────────────────
class EditPost(StatesGroup):
    waiting_text = State()

# ─── BOT ──────────────────────────────────────
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ─── ВСПОМОГАТЕЛЬНО ───────────────────────────
def split_text(text: str):
    return [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)]

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

# ─── ЗАГРУЗКА МЕДИА ───────────────────────────
async def download_media(msg: Message):
    """Сохраняет медиа в TEMP_DIR и возвращает путь к файлу"""
    os.makedirs(TEMP_DIR, exist_ok=True)

    if msg.content_type == ContentType.PHOTO:
        file_path = os.path.join(TEMP_DIR, f"{msg.message_id}.jpg")
        await msg.photo[-1].download(destination=file_path)
    elif msg.content_type == ContentType.VIDEO:
        file_path = os.path.join(TEMP_DIR, f"{msg.message_id}.mp4")
        await msg.video.download(destination=file_path)
    elif msg.content_type == ContentType.VOICE:
        file_path = os.path.join(TEMP_DIR, f"{msg.message_id}.ogg")
        await msg.voice.download(destination=file_path)
    elif msg.content_type == ContentType.DOCUMENT:
        ext = os.path.splitext(msg.document.file_name)[1]
        file_path = os.path.join(TEMP_DIR, f"{msg.message_id}{ext}")
        await msg.document.download(destination=file_path)
    else:
        return None

    log.info(f"Медиа сохранено: {file_path}")
    return file_path

# ─── START ────────────────────────────────────
@dp.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="История", callback_data="show_history")],
        [InlineKeyboardButton(text="Черновики", callback_data="show_drafts")]
    ])
    await msg.answer("Пришли пост для публикации", reply_markup=kb)

# ─── ПОСТЫ И ЧЕРНОВИКИ ───────────────────────
@dp.message()
async def receive_post(msg: Message):
    log.info(f"Получен пост type={msg.content_type}")
    text = msg.text or msg.caption or ""
    file_path = await download_media(msg)

    post_id = await save_message(msg.from_user.id, msg.chat.id, msg.message_id, text, msg.content_type, file_path=file_path)
    await set_status(post_id, "draft")

    await msg.answer("Выбери действие:", reply_markup=group_keyboard(post_id))

# ─── ИСТОРИЯ ─────────────────────────────────
@dp.callback_query(F.data == "show_history")
async def show_history(cb: CallbackQuery):
    posts = await get_history(cb.from_user.id)
    if not posts:
        await cb.message.answer("История пуста")
        await cb.answer()
        return

    text = "📊 История постов:\n\n"
    for p in posts:
        text += f"🆔 {p['id']} | {p['status']}\n{(p['caption'] or '')[:60]}\n\n"

    await cb.message.answer(text)
    await cb.answer()

# ─── ЧЕРНОВИКИ ───────────────────────────────
@dp.callback_query(F.data == "show_drafts")
async def show_drafts_cb(cb: CallbackQuery):
    drafts = await get_drafts(cb.from_user.id)
    if not drafts:
        await cb.message.answer("Черновики пусты")
        await cb.answer()
        return

    for d in drafts:
        await cb.message.answer(
            f"🆔 {d['id']} | {d['status']}\n{(d['caption'] or '')[:60]}",
            reply_markup=group_keyboard(d['id'])
        )
    await cb.answer()

# ─── РЕДАКТИРОВАНИЕ ───────────────────────────
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

# ─── ОТМЕНА ───────────────────────────────────
@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_post(cb: CallbackQuery):
    post_id = int(cb.data.split(":")[1])
    await set_status(post_id, "cancelled")
    log.info(f"Пост отменён post_id={post_id}")
    await cb.message.edit_text("❌ Публикация отменена")
    await cb.answer()

# ─── ВЫБОР ГРУППЫ ─────────────────────────────
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

# ─── ПЛАНИРОВАНИЕ ────────────────────────────
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

# ─── ПУБЛИКАЦИЯ ───────────────────────────────
async def publish(post_id):
    post = await get_post(post_id)
    if post["status"] == "cancelled":
        return

    target_chat_id = post["target_chat_id"] or post["chat_id"]
    text = post["caption"] or ""

    # Сообщение об успешной отправке в боте
    await bot.send_message(post["chat_id"], "✅ Пост успешно отправлен")

    # Публикация медиа + подписи
    if post.get("file_path") and os.path.exists(post["file_path"]):
        file_path = post["file_path"]
        if post["content_type"] == ContentType.PHOTO:
            await bot.send_photo(target_chat_id, photo=open(file_path, "rb"), caption=f"{text}\n\n{POST_FOOTER}")
        elif post["content_type"] == ContentType.VIDEO:
            await bot.send_video(target_chat_id, video=open(file_path, "rb"), caption=f"{text}\n\n{POST_FOOTER}")
        elif post["content_type"] == ContentType.VOICE:
            await bot.send_voice(target_chat_id, voice=open(file_path, "rb"), caption=f"{text}\n\n{POST_FOOTER}")
        elif post["content_type"] == ContentType.DOCUMENT:
            await bot.send_document(target_chat_id, document=open(file_path, "rb"), caption=f"{text}\n\n{POST_FOOTER}")
    else:
        # fallback на текст, если файл не найден
        await bot.send_message(target_chat_id, f"{text}\n\n{POST_FOOTER}")
        log.warning(f"Файл для post_id={post_id} не найден, отправляем текст")

    await set_status(post_id, "posted")
    log.info(f"ПОСТ ОТПРАВЛЕН post_id={post_id} в чат {target_chat_id}")

# ─── MAIN ─────────────────────────────────────
async def main():
    log.info("=== BOT STARTED ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
