import aiosqlite
import logging

log = logging.getLogger("DB")

DB_NAME = "posts.db"


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
            content_type TEXT
        )
        """)
        await db.commit()
    log.info("База данных готова")


async def save_message(user_id, chat_id, message_id, caption, content_type):
    log.info(f"Сохранение сообщения user_id={user_id}, message_id={message_id}")
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            """
            INSERT INTO posts (user_id, chat_id, message_id, caption, content_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, chat_id, message_id, caption, content_type)
        )
        await db.commit()
        return cur.lastrowid


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
