#db.py

import aiosqlite
import logging
from datetime import datetime

log = logging.getLogger("DB")
DB_NAME = "posts.db"

# ─── INIT ─────────────────────────────────────
async def init_db():
    log.info("Инициализация базы данных")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            message_id INTEGER,
            caption TEXT,
            content_type TEXT,
            status TEXT,
            job_id TEXT,
            created_at TEXT
        )
        """)
        await db.commit()
    log.info("База данных готова")

# ─── CREATE ───────────────────────────────────
async def save_message(user_id, chat_id, message_id, caption, content_type):
    log.info(f"Сохранение сообщения user_id={user_id}, message_id={message_id}")
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            """
            INSERT INTO posts (
                user_id, chat_id, message_id,
                caption, content_type,
                status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                chat_id,
                message_id,
                caption,
                content_type,
                "draft",
                datetime.now().isoformat()
            )
        )
        await db.commit()
        return cur.lastrowid

# ─── READ ─────────────────────────────────────
async def get_message(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            """
            SELECT chat_id, message_id, caption, content_type
            FROM posts WHERE id = ?
            """,
            (post_id,)
        )
        return await cur.fetchone()

async def get_post(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM posts WHERE id = ?",
            (post_id,)
        )
        return await cur.fetchone()

async def get_history(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, caption, status
            FROM posts
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (user_id,)
        )
        return await cur.fetchall()

# ─── GET DRAFTS ──────────────────────────────
async def get_drafts(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, caption, status
            FROM posts
            WHERE user_id = ? AND status = 'draft'
            ORDER BY id DESC
            """,
            (user_id,)
        )
        return await cur.fetchall()

# ─── UPDATE ───────────────────────────────────
async def update_text(post_id, text):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE posts SET caption = ? WHERE id = ?",
            (text, post_id)
        )
        await db.commit()

async def set_status(post_id, status):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id)
        )
        await db.commit()

async def set_job(post_id, job_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE posts SET job_id = ? WHERE id = ?",
            (job_id, post_id)
        )
        await db.commit()
