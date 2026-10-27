from __future__ import annotations

from app.config import get_settings
from app.db.database import init_db
from app.jobs.tasks import execute_job

__all__ = ["execute_job", "main"]


def main() -> None:
    settings = get_settings()
    init_db(settings.database_url)
    if not settings.redis_url:
        print(
            "REDIS_URL is not set; the API process executes jobs in its local ThreadPoolExecutor."
        )
        return
    from redis import Redis
    from rq import Worker

    connection = Redis.from_url(settings.redis_url)
    Worker(["alinea"], connection=connection).work()


if __name__ == "__main__":
    main()
