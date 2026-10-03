# Feature Flags and Dynamic Configuration Platform

Сделал за 3 дня по официальным документациям. Пульт директора: тумблеры и настройки без редеплоя. Hot-path `<5ms` через Redis.

Доки, по которым собирал:
- FastAPI — https://fastapi.tiangolo.com (lifespan, Depends, Pydantic v2)
- SQLAlchemy 2.0 — `mapped_column`, `async_sessionmaker`
- Redis — https://redis.io/tutorials/feature-flags-and-remote-config-with-redis/ (Hash + MGET pipeline + `sha256(key:user)%100`)
- Vue 3 + Pinia — https://vuejs.org + https://pinia.vuejs.org
- Docker Compose + Nginx — rate-limit, `internal: true` сеть

## Стек
FastAPI 0.119 · SQLAlchemy async + asyncpg · Redis 7.2 (hiredis) · Postgres 15 · Vue 3 + Pinia + Tailwind · Nginx 1.27 · Docker Compose

## Запуск
```bash
cp .env.example .env   # заполнить POSTGRES_PASSWORD, JWT_SECRET_KEY, ADMIN_PASSWORD
docker compose up --build -d
curl http://localhost/healthz
curl http://localhost/api/v1/admin/flags -H "Authorization: Bearer <JWT>"
```

## API
| Метод | Кто | Откуда |
|---|---|---|
| `POST /api/v1/auth/login` | все | JWT, Argon2 |
| `GET/POST/PATCH/DELETE /api/v1/admin/flags` | только admin | PG truth + write-through в Redis |
| `POST /api/v1/flags/evaluate` | публичный | только Redis MGET, fallback в PG |
| `GET /health`, `/ready`, `/docs` | — | healthcheck для Docker/Nginx |

## Безопасность
JWT + RBAC, Argon2, Pydantic-валидация (`^[a-z0-9_.-]+$`, max 100 ключей), CORS не `*`, Nginx rate-limit (auth 10r/s, eval 100r/s), PG/Redis в закрытой сети, Docker non-root, CI: ruff + bandit + pip-audit + trivy.

## Проверки
```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt
pytest -q            # 7 юнитов: killswitch, rollout 0/100, детерминизм
bandit -r app -ll    # 0 issues
k6 run ../infra/k6-evaluate.js  # gate p99<5ms
```

## Структура
- `backend/app/main.py` — API + auth + evaluate
- `backend/scripts/sync_pg_to_redis.py` — синк PG→Redis (`--once` / `--watch`)
- `frontend/src/` — Pinia store + Admin UI
- `infra/nginx/nginx.conf`, `infra/k6-evaluate.js` — proxy/LB + нагрузка
- `docker-compose.yml` — PG + Redis + backend + worker + frontend + Nginx

День 1 — compose + PG/Redis + модели. День 2 — auth + evaluate + синк. День 3 — админка + Nginx + CI/k6.
