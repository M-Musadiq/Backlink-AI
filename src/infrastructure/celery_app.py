"""Celery app configuration - task broker with Redis."""
from celery import Celery
from celery.schedules import crontab
from src.config import REDIS_URL
import ssl

# Append ssl_cert_reqs to URL for Celery Upstash compatibility
_broker_url = REDIS_URL
_backend_url = REDIS_URL
if _broker_url.startswith("rediss://"):
    sep = "&" if "?" in _broker_url else "?"
    _broker_url += f"{sep}ssl_cert_reqs=CERT_NONE"
    _backend_url += f"{sep}ssl_cert_reqs=CERT_NONE"

app = Celery(
    "backlink",
    broker=_broker_url,
    backend=_backend_url,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,
    task_time_limit=600,
)

app.autodiscover_tasks(["src.infrastructure.tasks"])

app.conf.beat_schedule = {
    "guidelines-refresh-weekly": {
        "task": "src.infrastructure.tasks.evaluation_tasks.refresh_guidelines",
        "schedule": crontab(hour=2, minute=0, day_of_week=0),
    },
    "follow-up-check": {
        "task": "src.infrastructure.tasks.crm_tasks.follow_up_check",
        "schedule": crontab(hour="*/4", minute=0),
    },
}
