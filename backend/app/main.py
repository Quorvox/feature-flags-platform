"""Feature Flags API: Admin CRUD (protected, PG truth) + Evaluate (public, Redis only)."""
from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import jwt
import orjson
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

log = logging.getLogger("flags")
ph = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://flags:flags@localhost:5432/flagsdb"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "dev-only-change-me-in-prod-32-chars-min"
    jwt_expire_minutes: int = 60
    admin_email: str = "admin@example.com"
    admin_password: str = "dev-only-change-me-16"
    log_level: str = "info"
    redis_prefix: str = "flag:v1:"


settings = Settings()


class Base(DeclarativeBase):
    pass


class FlagType(str, Enum):
    boolean = "boolean"
    number = "number"
    string = "string"
    json = "json"


class Flag(Base):
    __tablename__ = "flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default=FlagType.boolean.value)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    value: Mapped[Any] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=False)
    rollout_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
redis_client: Redis | None = None


async def get_db() -> AsyncSession:
    async with SessionLocal() as s:
        yield s


def get_redis() -> Redis:
    assert redis_client is not None, "redis not initialized"
    return redis_client


def redis_key(flag_key: str) -> str:
    return f"{settings.redis_prefix}{flag_key}"


def to_cache_payload(f: Flag) -> dict[str, Any]:
    return {
        "key": f.key,
        "type": f.type,
        "enabled": f.enabled,
        "value": f.value,
        "rollout_percentage": f.rollout_percentage,
        "version": f.version,
    }


async def cache_upsert(r: Redis, f: Flag) -> None:
    await r.set(redis_key(f.key), orjson.dumps(to_cache_payload(f)).decode())


async def cache_delete(r: Redis, key: str) -> None:
    await r.delete(redis_key(key))


def hash_password(raw: str) -> str:
    return ph.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return ph.verify(hashed, raw)
    except VerifyMismatchError:
        return False


def create_token(user_id: int, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    try:
        data = jwt.decode(creds.credentials, settings.jwt_secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    user = (await db.execute(select(User).where(User.id == int(data["sub"])))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user inactive")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FlagCreate(BaseModel):
    key: str = Field(min_length=2, max_length=128, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2000)
    type: FlagType = FlagType.boolean
    enabled: bool = False
    value: Any = False
    rollout_percentage: int = Field(default=100, ge=0, le=100)


class FlagUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    value: Any | None = None
    rollout_percentage: int | None = Field(default=None, ge=0, le=100)


class FlagOut(BaseModel):
    key: str
    name: str
    description: str
    type: str
    enabled: bool
    value: Any
    rollout_percentage: int
    version: int


class EvaluateItem(BaseModel):
    key: str
    enabled: bool
    value: Any
    reason: str


class EvaluateRequest(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)


class EvaluateResponse(BaseModel):
    flags: dict[str, EvaluateItem]


def in_rollout(flag_key: str, user_id: str, percentage: int) -> bool:
    if percentage >= 100:
        return True
    if percentage <= 0:
        return False
    digest = hashlib.sha256(f"{flag_key}:{user_id}".encode()).hexdigest()
    return (int(digest[:8], 16) % 100) < percentage


def default_off(payload: dict[str, Any]) -> Any:
    t = payload.get("type")
    if t == "boolean":
        return False
    if t == "number":
        return 0
    if t == "string":
        return ""
    return None


def resolve_flag(payload: dict[str, Any], context: dict[str, Any]) -> EvaluateItem:
    if not payload.get("enabled", False):
        return EvaluateItem(key=payload["key"], enabled=False, value=default_off(payload), reason="off_killswitch")
    user_id = str(context.get("user_id", context.get("userId", "anonymous")))
    if not in_rollout(payload["key"], user_id, int(payload.get("rollout_percentage", 100))):
        return EvaluateItem(key=payload["key"], enabled=False, value=default_off(payload), reason="off_rollout")
    return EvaluateItem(key=payload["key"], enabled=True, value=payload.get("value"), reason="on")


async def ensure_admin(db: AsyncSession) -> None:
    email = settings.admin_email.strip().lower()
    if len(settings.admin_password) < 12:
        log.warning("ADMIN_PASSWORD too short, bootstrap skipped")
        return
    exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if exists:
        return
    db.add(User(email=email, password_hash=hash_password(settings.admin_password), role="admin", is_active=True))
    await db.commit()
    log.info("bootstrap admin created: %s", email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logging.basicConfig(level=settings.log_level.upper())
    if len(settings.jwt_secret_key) < 32:
        log.warning("JWT_SECRET_KEY too short! Set 32+ chars in production.")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await ensure_admin(db)
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30)
    await redis_client.ping()
    log.info("startup ok")
    yield
    if redis_client:
        await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="Feature Flags API", version="1.0.0", default_response_class=ORJSONResponse, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    try:
        await db.execute(select(1))
        await get_redis().ping()
        return {"ready": True}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"not ready: {e}")


@app.post("/api/v1/auth/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = (await db.execute(select(User).where(User.email == body.email.strip().lower()))).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return TokenOut(access_token=create_token(user.id, user.email, user.role))


def row_to_out(f: Flag) -> FlagOut:
    return FlagOut(
        key=f.key, name=f.name, description=f.description, type=f.type,
        enabled=f.enabled, value=f.value, rollout_percentage=f.rollout_percentage, version=f.version,
    )


@app.post("/api/v1/admin/flags", response_model=FlagOut, status_code=status.HTTP_201_CREATED)
async def create_flag(body: FlagCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> FlagOut:
    exists = (await db.execute(select(Flag).where(Flag.key == body.key))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, f"flag '{body.key}' already exists")
    f = Flag(**body.model_dump())
    db.add(f)
    await db.commit()
    await db.refresh(f)
    await cache_upsert(get_redis(), f)
    return row_to_out(f)


@app.get("/api/v1/admin/flags", response_model=list[FlagOut])
async def list_flags(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> list[FlagOut]:
    rows = (await db.execute(select(Flag).order_by(Flag.key))).scalars().all()
    return [row_to_out(f) for f in rows]


@app.get("/api/v1/admin/flags/{key}", response_model=FlagOut)
async def get_flag(key: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> FlagOut:
    f = (await db.execute(select(Flag).where(Flag.key == key))).scalar_one_or_none()
    if not f:
        raise HTTPException(404, "flag not found")
    return row_to_out(f)


@app.patch("/api/v1/admin/flags/{key}", response_model=FlagOut)
async def update_flag(
    key: str, body: FlagUpdate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
) -> FlagOut:
    f = (await db.execute(select(Flag).where(Flag.key == key))).scalar_one_or_none()
    if not f:
        raise HTTPException(404, "flag not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(f, k, v)
    f.version += 1
    await db.commit()
    await db.refresh(f)
    await cache_upsert(get_redis(), f)
    return row_to_out(f)


@app.delete("/api/v1/admin/flags/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flag(key: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> None:
    f = (await db.execute(select(Flag).where(Flag.key == key))).scalar_one_or_none()
    if not f:
        raise HTTPException(404, "flag not found")
    await db.delete(f)
    await db.commit()
    await cache_delete(get_redis(), key)


@app.post("/api/v1/flags/evaluate", response_model=EvaluateResponse)
async def evaluate(body: EvaluateRequest) -> EvaluateResponse:
    r = get_redis()
    redis_keys = [redis_key(k) for k in body.keys]
    raw = await r.mget(redis_keys)
    out: dict[str, EvaluateItem] = {}
    misses: list[str] = []
    for req_key, blob in zip(body.keys, raw):
        if not blob:
            misses.append(req_key)
            continue
        payload = orjson.loads(blob)
        out[req_key] = resolve_flag(payload, body.context)
    if misses:
        async with SessionLocal() as db:
            rows = (await db.execute(select(Flag).where(Flag.key.in_(misses)))).scalars().all()
            found = {f.key: f for f in rows}
            if found:
                pipe = r.pipeline()
                for k, f in found.items():
                    pipe.set(redis_key(k), orjson.dumps(to_cache_payload(f)).decode())
                await pipe.execute()
            for k in misses:
                if k in found:
                    out[k] = resolve_flag(to_cache_payload(found[k]), body.context)
                else:
                    out[k] = EvaluateItem(key=k, enabled=False, value=None, reason="not_found")
    return EvaluateResponse(flags=out)


@app.get("/api/v1/flags/evaluate", response_model=EvaluateItem)
async def evaluate_single(
    key: str = Query(min_length=1, max_length=128),
    user_id: str = Query(default="anonymous", max_length=256),
) -> EvaluateItem:
    blob = await get_redis().get(redis_key(key))
    if not blob:
        async with SessionLocal() as db:
            f = (await db.execute(select(Flag).where(Flag.key == key))).scalar_one_or_none()
            if not f:
                return EvaluateItem(key=key, enabled=False, value=None, reason="not_found")
            await cache_upsert(get_redis(), f)
            return resolve_flag(to_cache_payload(f), {"user_id": user_id})
    return resolve_flag(orjson.loads(blob), {"user_id": user_id})
