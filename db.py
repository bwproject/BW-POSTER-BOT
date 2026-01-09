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
            caption TEXT
        )
        """)
        await db.commit()
    log.info("База данных готова")


async def save_message(user_id, chat_id, message_id, caption=None):
    log.info(f"Сохранение сообщения user_id={user_id}, message_id={message_id}")
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "INSERT INTO posts (user_id, chat_id, message_id, caption) VALUES (?, ?, ?, ?)",
            (user_id, chat_id, message_id, caption)
        )
        await db.commit()
        post_id = cur.lastrowid
    log.info(f"Сообщение сохранено post_id={post_id}")
    return post_id


async def get_message(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "SELECT chat_id, message_id, caption FROM posts WHERE id = ?",
            (post_id,)
        )
        return await cur.fetchone()


async def update_caption(post_id, caption):
    log.info(f"Обновление текста post_id={post_id}")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE posts SET caption = ? WHERE id = ?",
            (caption, post_id)
        )
        await db.commit()
