from rq import Worker

from app.queue.redis_conn import default_queue, redis_conn

if __name__ == "__main__":
    Worker([default_queue], connection=redis_conn).work()
