from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.config import Settings, get_settings

_executor: ThreadPoolExecutor | None = None
_lock = Lock()


def initialize_dispatcher(settings: Settings | None = None) -> None:
    global _executor
    settings = settings or get_settings()
    with _lock:
        if settings.redis_url:
            return
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=settings.local_workers,
                thread_name_prefix="alinea-job",
            )


def dispatch_job(job_id: str) -> None:
    settings = get_settings()
    if settings.redis_url:
        from redis import Redis
        from rq import Queue

        connection = Redis.from_url(settings.redis_url)
        queue = Queue("alinea", connection=connection)
        queue.enqueue("app.worker.execute_job", job_id, job_id=job_id, job_timeout=600)
        return
    initialize_dispatcher(settings)
    assert _executor is not None
    from app.jobs.tasks import execute_job

    _executor.submit(execute_job, job_id)


def shutdown_dispatcher() -> None:
    global _executor
    with _lock:
        executor = _executor
        _executor = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=False)
