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
    init_db, save_message, get_post, get_history,
    update_text, set_status, set_job
)
from scheduler import scheduler, start_scheduler

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

# ─── ВСПОМОГАТЕЛЬНО ───────────────────
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

def schedule_keyboard(post_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("Сейчас", callback_data=f"now:{post_id}"),
            InlineKeyboardButton("+5 мин", callback_data=f"delay:{post_id}:5"),
            InlineKeyboardButton("+10 мин", callback_data=f"delay:{post_id}:10"),
        ],
        [
            InlineKeyboardButton("+20 мин", callback_data=f"delay:{post_id}:20"),
            InlineKeyboardButton("+30 мин", callback_data=f"delay:{post_id}:30"),
            InlineKeyboardButton("+60 мин", callback_data=f"delay:{post_id}:60"),
        ],
        [
            InlineKeyboardButton("Выбрать дату/время", callback_data=f"schedule_custom:{post_id}")
        ]
    ])

user_datetime = {}  # для выбора даты/времени через календарь

# ─── START ─────────────────────────────
@dp.message(Command("start"))
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Черновики", callback_data="show_drafts")],
        [InlineKeyboardButton("История", callback_data="show_history")]
    ])
    await msg.answer("Пришлите пост для публикации", reply_markup=kb)

# ─── ИСТОРИЯ ──────────────────────────
@dp.callback_query(F.data=="show_history")
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

# ─── ЧЕРНОВИКИ ─────────────────────────
@dp.callback_query(F.data=="show_drafts")
async def show_drafts(cb: CallbackQuery):
    posts = await get_history(cb.from_user.id)
    drafts = [p for p in posts if p['status']=='draft']
    if not drafts:
        await cb.message.answer("Черновики пусты")
        await cb.answer()
        return
    for p in drafts:
        await cb.message.answer(
            f"🆔 {p['id']}\n{(p['caption'] or '')[:60]}...",
            reply_markup=group_keyboard(p['id'])
        )
    await cb.answer()

# ─── ПОЛУЧЕНИЕ ПОСТА ─────────────────────
@dp.message()
async def receive_post(msg: Message):
    log.info(f"Получен пост type={msg.content_type}")
    text = msg.text or msg.caption or ""
    text = text + "\n\n" + POST_FOOTER
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
    text = msg.text + "\n\n" + POST_FOOTER
    await update_text(post_id, text)
    await set_status(post_id, "draft")
    log.info(f"Текст обновлён post_id={post_id}")
    await state.clear()
    await msg.answer("✅ Текст обновлён")

# ─── ОТМЕНА ─────────────────────────────
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

# ─── ВЫБОР ГРУППЫ ───────────────────────
@dp.callback_query(F.data.startswith("group:"))
async def choose_group(cb: CallbackQuery):
    _, post_id, group = cb.data.split(":")
    kb = schedule_keyboard(post_id)
    await cb.message.edit_text("Выберите когда публикуем:", reply_markup=kb)
    await cb.answer()

# ─── ПУБЛИКАЦИЯ СРАЗУ ИЛИ ЗАДЕРЖКА ─────────
@dp.callback_query(F.data.startswith("now:"))
async def post_now(cb: CallbackQuery):
    post_id = int(cb.data.split(":")[1])
    post = await get_post(post_id)
    group = post['chat_id']  # отправляем в оригинальный чат
    await publish(post_id, group)
    await cb.message.edit_text("✅ Опубликовано")
    await cb.answer()

@dp.callback_query(F.data.startswith("delay:"))
async def post_delay(cb: CallbackQuery):
    _, post_id, minutes = cb.data.split(":")
    post_id = int(post_id)
    minutes = int(minutes)
    post = await get_post(post_id)
    run_at = datetime.now() + timedelta(minutes=minutes)
    job_id = str(uuid.uuid4())
    scheduler.add_job(
        publish,
        trigger="date",
        run_date=run_at,
        args=(post_id, post['chat_id']),
        id=job_id
    )
    await set_job(post_id, job_id)
    await set_status(post_id, "scheduled")
    log.info(f"Пост запланирован post_id={post_id} на {run_at}")
    await cb.message.edit_text(f"⏰ Запланировано на {run_at.strftime('%d.%m.%Y %H:%M')}")
    await cb.answer()

# ─── ВЫБОР КАЛЕНДАРЯ ─────────────────────
@dp.callback_query(F.data.startswith("schedule_custom:"))
async def ask_datetime(cb: CallbackQuery):
    post_id = int(cb.data.split(":")[1])
    user_datetime[cb.from_user.id] = {"post_id": post_id}
    now = datetime.now()
    await cb.message.edit_text("Выберите день:", reply_markup=calendar_keyboard(now.year, now.month))
    await cb.answer()

# ─── ФУНКЦИИ КАЛЕНДАРЯ ───────────────────
import calendar

def calendar_keyboard(year, month):
    kb = InlineKeyboardMarkup(row_width=7)
    cal = calendar.Calendar()
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"calendar:{year}:{month}:{day}"))
        kb.add(*row)
    prev_month = month - 1 if month > 1 else 12
    next_month = month + 1 if month < 12 else 1
    kb.add(
        InlineKeyboardButton("⬅️", callback_data=f"calendar_nav:{year}:{prev_month}"),
        InlineKeyboardButton("➡️", callback_data=f"calendar_nav:{year}:{next_month}")
    )
    return kb

@dp.callback_query(F.data.startswith("calendar:"))
async def choose_day(cb: CallbackQuery):
    _, year, month, day = cb.data.split(":")
    user_datetime[cb.from_user.id].update({"year": int(year), "month": int(month), "day": int(day)})
    await cb.message.edit_text("Введите час (0-23):")
    await cb.answer()

@dp.message()
async def choose_hour(msg: Message):
    if msg.text.isdigit() and 0 <= int(msg.text) <= 23 and msg.from_user.id in user_datetime:
        user_datetime[msg.from_user.id]["hour"] = int(msg.text)
        await msg.answer("Введите минуты (0-59):")
    elif msg.from_user.id in user_datetime:
        await msg.answer("Введите корректный час (0-23)")

@dp.message()
async def choose_minute(msg: Message):
    if msg.text.isdigit() and 0 <= int(msg.text) <= 59 and msg.from_user.id in user_datetime:
        data = user_datetime.pop(msg.from_user.id)
        post_id = data["post_id"]
        run_at = datetime(data["year"], data["month"], data["day"], data["hour"], int(msg.text))
        post = await get_post(post_id)
        job_id = str(uuid.uuid4())
        scheduler.add_job(
            publish,
            trigger="date",
            run_date=run_at,
            args=(post_id, post['chat_id']),
            id=job_id
        )
        await set_job(post_id, job_id)
        await set_status(post_id, "scheduled")
        log.info(f"Пост запланирован post_id={post_id} на {run_at}")
        await msg.answer(f"⏰ Запланировано на {run_at.strftime('%d.%m.%Y %H:%M')}")
    elif msg.from_user.id in user_datetime:
        await msg.answer("Введите корректные минуты (0-59)")

# ─── ПУБЛИКАЦИЯ ─────────────────────────────
async def publish(post_id: int, target):
    post = await get_post(post_id)
    if post["status"] == "cancelled":
        return
    if post["content_type"] == ContentType.TEXT:
        parts = split_text(post["caption"])
        for p in parts:
            await bot.send_message(target, p)
    else:
        await bot.copy_message(
            chat_id=target,
            from_chat_id=post['chat_id'],
            message_id=post['message_id'],
            caption=post["caption"]
        )
    await set_status(post_id, "posted")
    log.info(f"ПОСТ ОТПРАВЛЕН post_id={post_id}")

# ─── MAIN ─────────────────────────────
async def main():
    log.info("=== BOT STARTED ===")
    await init_db()
    start_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
