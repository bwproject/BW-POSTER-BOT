import asyncio
import logging
from datetime import datetime, timedelta
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from config import BOT_TOKEN, GROUPS, POST_FOOTER, MAX_TEXT
from db import (
    init_db, save_message, get_message,
    update_text, set_status, set_job,
    get_history, get_post, get_drafts
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

class SchedulePost(StatesGroup):
    waiting_datetime = State()
    post_id = State()
    group = State()

# ─── BOT ──────────────────────────────────────
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ─── ВСПОМОГАТЕЛЬНО ───────────────────────────
def split_text(text: str):
    return [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)]

def group_keyboard(post_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("MrMes", callback_data=f"group:{post_id}:The_Mr_Mes109"),
            InlineKeyboardButton("ProjectBW", callback_data=f"group:{post_id}:ProjectBW"),
            InlineKeyboardButton("Помойка", callback_data=f"group:{post_id}:Помойка")
        ],
        [
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{post_id}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"cancel:{post_id}")
        ]
    ])

def schedule_keyboard(post_id: int, group: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("Сейчас", callback_data=f"schedule:{post_id}:{group}:0"),
            InlineKeyboardButton("+5 мин", callback_data=f"schedule:{post_id}:{group}:5"),
            InlineKeyboardButton("+10 мин", callback_data=f"schedule:{post_id}:{group}:10")
        ],
        [
            InlineKeyboardButton("+20 мин", callback_data=f"schedule:{post_id}:{group}:20"),
            InlineKeyboardButton("+30 мин", callback_data=f"schedule:{post_id}:{group}:30"),
            InlineKeyboardButton("+60 мин", callback_data=f"schedule:{post_id}:{group}:60")
        ],
        [
            InlineKeyboardButton("Выбрать дату/время", callback_data=f"choose_datetime:{post_id}:{group}")
        ]
    ])

# ─── START ────────────────────────────────────
@dp.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("/history", callback_data="history")],
        [InlineKeyboardButton("/drafts", callback_data="drafts")]
    ])
    await msg.answer("Пришли пост для публикации", reply_markup=kb)

# ─── HISTORY ──────────────────────────────────
@dp.callback_query(F.data == "history")
@dp.message(Command("history"))
async def history(msg_or_cb):
    user_id = msg_or_cb.from_user.id
    posts = await get_history(user_id)
    if not posts:
        text = "История пуста"
    else:
        text = "📊 История постов:\n\n"
        for p in posts:
            text += f"🆔 {p['id']} | {p['status']}\n{(p['caption'] or '')[:60]}\n\n"

    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text)
    else:
        await msg_or_cb.message.answer(text)
        await msg_or_cb.answer()

# ─── DRAFTS ──────────────────────────────────
@dp.callback_query(F.data == "drafts")
@dp.message(Command("drafts"))
async def drafts(msg_or_cb):
    user_id = msg_or_cb.from_user.id
    posts = await get_drafts(user_id)
    if not posts:
        text = "Черновики пусты"
    else:
        text = "📝 Черновики:\n\n"
        for p in posts:
            text += f"🆔 {p['id']}\n{(p['caption'] or '')[:60]}\n\n"

    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text)
    else:
        await msg_or_cb.message.answer(text)
        await msg_or_cb.answer()

# ─── RECEIVE POST ───────────────────────────
@dp.message()
async def receive_post(msg: Message):
    log.info(f"Получен пост type={msg.content_type}")
    text = msg.text or msg.caption or ""
    if text:
        text += "\n\n" + POST_FOOTER

    post_id = await save_message(
        msg.from_user.id,
        msg.chat.id,
        msg.message_id,
        text,
        msg.content_type
    )
    await set_status(post_id, "draft")

    await msg.answer(
        "Выбери действие:",
        reply_markup=group_keyboard(post_id)
    )

# ─── EDIT POST ───────────────────────────────
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
    text = msg.text + "\n\n" + POST_FOOTER
    await update_text(post_id, text)
    await set_status(post_id, "draft")
    log.info(f"Текст обновлён post_id={post_id}")
    await state.clear()
    await msg.answer("✅ Текст обновлён")

# ─── CANCEL POST ─────────────────────────────
@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_post(cb: CallbackQuery):
    post_id = int(cb.data.split(":")[1])
    post = await get_post(post_id)
    if post["status"] == "scheduled" and post.get("job_id"):
        scheduler.remove_job(post["job_id"])
    await set_status(post_id, "cancelled")
    log.info(f"Пост отменён post_id={post_id}")
    await cb.message.edit_text("❌ Публикация отменена")
    await cb.answer()

# ─── CHOOSE GROUP ───────────────────────────
@dp.callback_query(F.data.startswith("group:"))
async def choose_group(cb: CallbackQuery):
    _, post_id, group = cb.data.split(":")
    await cb.message.edit_text(
        "Когда публикуем?",
        reply_markup=schedule_keyboard(post_id, group)
    )
    await cb.answer()

# ─── SCHEDULE / NOW ─────────────────────────
@dp.callback_query(F.data.startswith("schedule:"))
async def schedule_post_cb(cb: CallbackQuery):
    _, post_id, group, minutes = cb.data.split(":")
    minutes = int(minutes)
    if minutes == 0:
        await publish(int(post_id), group)
        await cb.message.edit_text("✅ Опубликовано")
    else:
        job_id = str(uuid.uuid4())
        run_at = datetime.now() + timedelta(minutes=minutes)
        scheduler.add_job(
            publish,
            trigger="date",
            run_date=run_at,
            args=(int(post_id), group),
            id=job_id
        )
        await set_job(int(post_id), job_id)
        await set_status(int(post_id), "scheduled")
        log.info(f"Пост запланирован post_id={post_id} на {run_at}")
        await cb.message.edit_text(f"⏰ Запланировано через {minutes} мин")
    await cb.answer()

# ─── CHOOSE DATE/TIME ───────────────────────
@dp.callback_query(F.data.startswith("choose_datetime:"))
async def ask_datetime(cb: CallbackQuery, state: FSMContext):
    _, post_id, group = cb.data.split(":")
    await state.update_data(post_id=int(post_id), group=group)
    await cb.message.answer("⏳ Пришли дату и время в формате: YYYY-MM-DD HH:MM")
    await state.set_state(SchedulePost.waiting_datetime)
    await cb.answer()

@dp.message(SchedulePost.waiting_datetime)
async def schedule_by_datetime(msg: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data["post_id"]
    group = data["group"]
    try:
        dt = datetime.strptime(msg.text, "%Y-%m-%d %H:%M")
    except:
        await msg.answer("❌ Неверный формат! Используй YYYY-MM-DD HH:MM")
        return
    job_id = str(uuid.uuid4())
    scheduler.add_job(
        publish,
        trigger="date",
        run_date=dt,
        args=(post_id, group),
        id=job_id
    )
    await set_job(post_id, job_id)
    await set_status(post_id, "scheduled")
    await state.clear()
    log.info(f"Пост запланирован post_id={post_id} на {dt}")
    await msg.answer(f"✅ Запланировано на {dt}")

# ─── PUBLISH ────────────────────────────────
async def publish(post_id: int, group: str):
    post = await get_post(post_id)
    if post["status"] == "cancelled":
        return
    await smart_send(
        GROUPS[group],
        post["chat_id"],
        post["message_id"],
        post["caption"],
        post["content_type"]
    )
    await set_status(post_id, "posted")
    log.info(f"ПОСТ ОТПРАВЛЕН post_id={post_id}")

# ─── SMART SEND ─────────────────────────────
async def smart_send(target, source_chat, msg_id, text, content_type):
    parts = split_text(text)
    if content_type == ContentType.TEXT:
        for p in parts:
            await bot.send_message(target, p)
        return
    await bot.copy_message(
        chat_id=target,
        from_chat_id=source_chat,
        message_id=msg_id,
        caption=parts[0] if parts else None
    )
    for p in parts[1:]:
        await bot.send_message(target, p)

# ─── MAIN ───────────────────────────────────
async def main():
    log.info("=== BOT STARTED ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
