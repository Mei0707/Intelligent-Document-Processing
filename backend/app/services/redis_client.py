from functools import lru_cache
from redis import Redis
from ..config import settings


@lru_cache(maxsize=1)
def redis_client():
    return Redis.from_url(settings.redis_url, decode_responses=True,
                          socket_connect_timeout=2, socket_timeout=3)
