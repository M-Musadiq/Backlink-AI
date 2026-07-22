import redis
from src.config import REDIS_URL

redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def get_redis():
    return redis_client
