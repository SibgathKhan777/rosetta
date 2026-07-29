from redis import Redis
from rq import Queue

from app.core.config import settings

redis_conn = Redis.from_url(settings.redis_url)

# Single queue for now. Stage 5 fans out chunk/frame sub-tasks onto this same
# queue using rq.job.Dependency for the fan-in back into the stitch step.
default_queue = Queue("default", connection=redis_conn)
