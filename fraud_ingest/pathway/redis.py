import redis
import os
from dotenv import load_dotenv

load_dotenv()

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

_update_profile_script = redis_client.register_script("""
    local key = KEYS[1]
    local amount = tonumber(ARGV[1])
    local is_fraud = tonumber(ARGV[2])
    local ttl = tonumber(ARGV[3])

    redis.call('HINCRBY', key, 'count', 1)
    redis.call('HINCRBYFLOAT', key, 'sum', amount)
    redis.call('HINCRBYFLOAT', key, 'sum_sq', amount * amount)

    if is_fraud > 0 then
        redis.call('HINCRBY', key, 'fraud_count', 1)
    end

    local current_max = tonumber(redis.call('HGET', key, 'max') or 0)
    if amount > current_max then
        redis.call('HSET', key, 'max', amount)
    end

    local current_min_str = redis.call('HGET', key, 'min')
    if not current_min_str then
        redis.call('HSET', key, 'min', amount)
    else
        local current_min = tonumber(current_min_str)
        if amount < current_min then
            redis.call('HSET', key, 'min', amount)
        end
    end

    redis.call('EXPIRE', key, ttl)

    return 1
""")

_update_velocity_script = redis_client.register_script("""
    local key = KEYS[1]
    local amount = tonumber(ARGV[1])
    local ttl = tonumber(ARGV[2])

    redis.call('HINCRBY', key, 'count', 1)
    redis.call('HINCRBYFLOAT', key, 'sum', amount)
    redis.call('EXPIRE', key, ttl)

    return 1
""")


def get_user_profile(user_id: str) -> dict:
    data = redis_client.hgetall(f"user:{user_id}")

    if not data:
        return {
            "count": 0, "sum": 0.0, "sum_sq": 0.0,
            "max": 0.0, "min": 0.0, "fraud_count": 0
        }

    return {
        "count": int(data.get("count", 0)),
        "sum": float(data.get("sum", 0.0)),
        "sum_sq": float(data.get("sum_sq", 0.0)),
        "max": float(data.get("max", 0.0)),
        "min": float(data.get("min", 0.0)),
        "fraud_count": int(data.get("fraud_count", 0))
    }


def get_step_velocity(user_id: str, step: int) -> dict:
    data = redis_client.hgetall(f"user:{user_id}:step:{step}")
    if not data:
        return {"count": 0, "sum": 0.0}

    return {
        "count": int(data.get("count", 0)),
        "sum": float(data.get("sum", 0.0))
    }


def update_redis_state(user_id: str, step: int, amount: float, is_fraud: int):
    try:
        _update_profile_script(
            keys=[f"user:{user_id}"],
            args=[amount, is_fraud, 1800]
        )

        _update_velocity_script(
            keys=[f"user:{user_id}:step:{step}"],
            args=[amount, 600]
        )

        return 1
    except Exception as e:
        print(f"Redis update failed: {e}")
        return 0
