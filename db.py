import aiosqlite

DB_NAME = "posts.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            message_id INTEGER
        )
        """)
        await db.commit()


async def save_message(user_id, chat_id, message_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "INSERT INTO posts (user_id, chat_id, message_id) VALUES (?, ?, ?)",
            (user_id, chat_id, message_id)
        )
        await db.commit()
        return cur.lastrowid


async def get_message(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "SELECT chat_id, message_id FROM posts WHERE id = ?",
            (post_id,)
        )
        return await cur.fetchone()
