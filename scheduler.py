from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging

log = logging.getLogger("SCHEDULER")

scheduler = AsyncIOScheduler()


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        log.info("Планировщик запущен")
