from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()


@scheduler.scheduled_job("cron", hour=6)
def scheduled_job() -> None:
    from .main import run_daily_sync

    print("⏰ Running daily sync job...")
    run_daily_sync()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
