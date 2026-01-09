import asyncio
import logging
import uuid
from datetime import datetime, timedelta

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
    init_db, save_message, get_post, get_history, get_drafts,
    update_text, set_status, set_job
)
from scheduler import scheduler, start_scheduler

# ─── ЛОГИ ───────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("BOT")

# ─── FSM ─────────────────────────────────
class EditPost(StatesGroup):
    waiting_text = State()

# ─── BOT ─────────────────────────────────
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ─── ВСПОМОГАТЕЛЬНО ─────────────────────
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
            InlineKeyboardButton("Сейчас", callback_data=f"now:{post_id}:{group}"),
            InlineKeyboardButton("+5 мин", callback_data=f"delay:{post_id}:{group}:5")
        ],
        [
            InlineKeyboardButton("+10 мин", callback_data=f"delay:{post_id}:{group}:10"),
            InlineKeyboardButton("+20 мин", callback_data=f"delay:{post_id}:{group}:20")
        ],
        [
            InlineKeyboardButton("+30 мин", callback_data=f"delay:{post_id}:{group}:30"),
            InlineKeyboardButton("+60 мин", callback_data=f"delay:{post_id}:{group}:60")
        ],
        [
            InlineKeyboardButton("Выбрать дату/время", callback_data=f"pick_datetime:{post_id}:{group}")
        ]
    ])

# ─── START ──────────────────────────────
@dp.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("История", callback_data="show_history")],
        [InlineKeyboardButton("Черновики", callback_data="show_drafts")]
    ])
    await msg.answer("Пришли пост для публикации", reply_markup=kb)

# ─── ИСТОРИЯ ────────────────────────────
@dp.callback_query(F.data=="show_history")
async def show_history(cb: CallbackQuery):
    posts = await get_history(cb.from_user.id)
    if not posts:
        await cb.message.answer("История пуста")
        return
    text = "📊 История постов:\n\n"
    for p in posts:
        text += f"🆔 {p['id']} | {p['status']}\n{(p['caption'] or '')[:60]}\n\n"
    await cb.message.answer(text)
    await cb.answer()

# ─── ЧЕРНОВИКИ ─────────────────────────
@dp.callback_query(F.data=="show_drafts")
async def show_drafts_cb(cb: CallbackQuery):
    posts = await get_drafts(cb.from_user.id)
    if not posts:
        await cb.message.answer("Черновиков нет")
        await cb.answer()
        return
    for p in posts:
        await cb.message.answer(
            f"🆔 {p['id']}\n{p['caption'][:100]}...",
            reply_markup=group_keyboard(p['id'])
        )
    await cb.answer()

# ─── ПОЛУЧЕНИЕ ПОСТА ───────────────────
@dp.message()
async def receive_post(msg: Message):
    log.info(f"Получен пост type={msg.content_type}")
    text = msg.text or msg.caption or ""
    text += f"\n\n{POST_FOOTER}"  # добавляем подпись

    post_id = await save_message(
        msg.from_user.id,
        msg.chat.id,
        msg.message_id,
        text,
        msg.content_type
    )
    await set_status(post_id, "draft")
    await msg.answer("Выбери действие:", reply_markup=group_keyboard(post_id))

# ─── РЕДАКТИРОВАНИЕ ─────────────────────
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
    text = msg.text + f"\n\n{POST_FOOTER}"
    await update_text(post_id, text)
    await set_status(post_id, "draft")
    log.info(f"Текст обновлён post_id={post_id}")
    await state.clear()
    await msg.answer("✅ Текст обновлён")

# ─── ОТМЕНА ────────────────────────────
@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_post(cb: CallbackQuery):
    post_id = int(cb.data.split(":")[1])
    post = await get_post(post_id)
    if post["status"] == "scheduled" and post["job_id"]:
        scheduler.remove_job(post["job_id"])
    await set_status(post_id, "cancelled")
    log.info(f"Пост отменён post_id={post_id}")
    await cb.message.edit_text("❌ Публикация отменена")
    await cb.answer()

# ─── ВЫБОР ГРУППЫ ──────────────────────
@dp.callback_query(F.data.startswith("group:"))
async def choose_group(cb: CallbackQuery):
    _, post_id, group = cb.data.split(":")
    kb = schedule_keyboard(post_id, group)
    await cb.message.edit_text("Когда публикуем?", reply_markup=kb)
    await cb.answer()

# ─── СЕЙЧАС ────────────────────────────
@dp.callback_query(F.data.startswith("now:"))
async def post_now(cb: CallbackQuery):
    _, post_id, group = cb.data.split(":")
    await publish(int(post_id), group)
    await cb.message.edit_text("✅ Опубликовано")
    await cb.answer()

# ─── С ЗАДЕРЖКОЙ ───────────────────────
@dp.callback_query(F.data.startswith("delay:"))
async def post_delay(cb: CallbackQuery):
    _, post_id, group, minutes = cb.data.split(":")
    minutes = int(minutes)
    run_at = datetime.now() + timedelta(minutes=minutes)
    job_id = str(uuid.uuid4())
    scheduler.add_job(publish, trigger="date", run_date=run_at, args=(int(post_id), group), id=job_id)
    await set_job(int(post_id), job_id)
    await set_status(int(post_id), "scheduled")
    log.info(f"Пост запланирован post_id={post_id} на +{minutes} мин в группу {group}")
    await cb.message.edit_text(f"⏰ Запланировано через {minutes} минут")
    await cb.answer()

# ─── ПУБЛИКАЦИЯ ─────────────────────────
async def publish(post_id: int, group: str):
    post = await get_post(post_id)
    if post["status"] == "cancelled":
        return
    parts = split_text(post["caption"])
    if post["content_type"] == ContentType.TEXT:
        for p in parts:
            await bot.send_message(GROUPS[group], p)
    else:
        await bot.copy_message(
            chat_id=GROUPS[group],
            from_chat_id=post["chat_id"],
            message_id=post["message_id"],
            caption=parts[0] if parts else None
        )
        for p in parts[1:]:
            await bot.send_message(GROUPS[group], p)
    await set_status(post_id, "posted")
    log.info(f"ПОСТ ОТПРАВЛЕН post_id={post_id} в группу {group}")

# ─── MAIN ───────────────────────────────
async def main():
    log.info("=== BOT STARTED ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
