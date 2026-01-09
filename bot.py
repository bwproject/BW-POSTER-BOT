#bot.py https://github.com/bwproject/BW-POSTER-BOT/edit/main/bot.py

import asyncio
import logging
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
    post_id = await save_message(msg.from_user.id, msg.chat.id, msg.message_id, text, msg.content_type)
    await set_status(post_id, "draft")

    await msg.answer("Выбери действие:", reply_markup=group_keyboard(post_id))

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

    target_chat_id = post["target_chat_id"]
    if not target_chat_id:
        log.warning(f"Не указан target_chat_id для post_id={post_id}")
        return

    # 1️⃣ Отправка в канал/группу с футером
    await smart_send(target_chat_id, post["chat_id"], post_id, post["caption"], post["content_type"], include_footer=True)

    # 2️⃣ Сообщение автору и сам пост обратно в бота
    await bot.send_message(post["chat_id"], "✅ Пост успешно отправлен")
    await smart_send(post["chat_id"], post["chat_id"], post_id, post["caption"], post["content_type"], include_footer=True)

    await set_status(post_id, "posted")
    log.info(f"ПОСТ ОТПРАВЛЕН post_id={post_id} в чат {target_chat_id}")


# ─── SMART SEND ───────────────────────────────
async def smart_send(target, source_chat, msg_id, text, content_type, include_footer=True):
    full_text = f"{text}\n\n{POST_FOOTER}" if include_footer else text
    parts = [full_text[i:i + MAX_TEXT] for i in range(0, len(full_text), MAX_TEXT)]

    if content_type == ContentType.TEXT:
        for p in parts:
            await bot.send_message(target, p, parse_mode="HTML", disable_web_page_preview=True)
        return

    await bot.copy_message(
        chat_id=target,
        from_chat_id=source_chat,
        message_id=msg_id,
        caption=parts[0] if parts else None,
        parse_mode="HTML"
    )
    for p in parts[1:]:
        await bot.send_message(target, p, parse_mode="HTML", disable_web_page_preview=True)


# ─── MAIN ─────────────────────────────────────
async def main():
    log.info("=== BOT STARTED ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
