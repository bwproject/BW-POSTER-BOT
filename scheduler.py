from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging

log = logging.getLogger("SCHEDULER")

scheduler = AsyncIOScheduler()


def start_scheduler():
    scheduler.start()
    log.info("Планировщик запущен")
