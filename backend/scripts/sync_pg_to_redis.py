"""Sync all flags from PostgreSQL (truth) to Redis (cache)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import orjson
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import Flag, redis_key, to_cache_payload  # noqa: E402

log = logging.getLogger("sync")


async def sync_once(database_url: str, redis_url: str) -> int:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    r = Redis.from_url(redis_url, decode_responses=True)
    try:
        async with maker() as db:
            rows = (await db.execute(select(Flag))).scalars().all()
        pipe = r.pipeline(transaction=False)
        for f in rows:
            pipe.set(redis_key(f.key), orjson.dumps(to_cache_payload(f)).decode())
        await pipe.execute()
        log.info("synced %d flags pg -> redis", len(rows))
        return len(rows)
    finally:
        await r.aclose()
        await engine.dispose()


async def amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--interval", type=int, default=30)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db_url = os.environ["DATABASE_URL"]
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    if a.watch:
        while True:
            try:
                await sync_once(db_url, redis_url)
            except Exception:
                log.exception("sync failed, will retry")
            await asyncio.sleep(a.interval)
    else:
        await sync_once(db_url, redis_url)


if __name__ == "__main__":
    asyncio.run(amain())
