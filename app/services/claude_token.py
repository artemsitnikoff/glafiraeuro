"""Claude OAuth token auto-refresh.

Хранит access + refresh токены в data/.claude_token.json.
Refresh-токены одноразовые — ротируются при каждом обновлении.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger("glafira")

TOKEN_FILE = Path("data/.claude_token.json")
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
REFRESH_BUFFER_MS = 600_000

_refresh_lock = asyncio.Lock()


def _static_token() -> str | None:
    """Долгоживущий OAuth-токен (`sk-ant-oat01-…`, ~1 год) из .env.

    Если задан `CLAUDE_CODE_OAUTH_TOKEN` и НЕ задан `CLAUDE_REFRESH_TOKEN` —
    включается «статический режим»: берём токен прямо из env, НЕ читаем и НЕ
    пишем общий `data/.claude_token.json` и НЕ рефрешим вообще.

    Зачем: на проде `data/` — симлинк на `~/ArkadyJarvis/data`, файл
    `.claude_token.json` общий с соседним ботом. Refresh-токены одноразовые,
    а login/setup-token ротируют грант → при авто-рефреше проекты отзывали
    токен друг у друга (401 invalid credentials / 400 на /oauth/token).
    Долгоживущий токен + отказ от рефреша эту гонку убирает.

    ⚠️ В этом режиме НЕЛЬЗЯ делать `claude login/setup-token/logout` на том же
    аккаунте — это отзовёт токен у обоих ботов.
    """
    token = (settings.claude_code_oauth_token or "").strip()
    refresh = (settings.claude_refresh_token or "").strip()
    if token and not refresh:
        return token
    return None


def _load() -> dict:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(TOKEN_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, TOKEN_FILE)


def init_token_file() -> None:
    static = _static_token()
    if static:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = static
        logger.info(
            "Claude: статический долгоживущий токен из env — общий "
            "data/.claude_token.json не используется, авто-рефреш выключен"
        )
        return

    if TOKEN_FILE.exists():
        data = _load()
        if data.get("refresh_token"):
            logger.info("Claude token file exists with refresh token")
            return

    access_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    refresh_token = os.environ.get("CLAUDE_REFRESH_TOKEN", "")

    if not refresh_token:
        if access_token:
            logger.warning(
                "CLAUDE_CODE_OAUTH_TOKEN set but no CLAUDE_REFRESH_TOKEN — "
                "token will not auto-refresh"
            )
        return

    _save({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": 0,
    })
    logger.info("Claude token file initialized from env vars")


async def ensure_fresh_token() -> None:
    static = _static_token()
    if static:
        # Статический режим: токен из env, никаких файлов и рефреша.
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = static
        return

    async with _refresh_lock:
        data = _load()
        now_ms = time.time() * 1000

        if data.get("expires_at", 0) > now_ms + REFRESH_BUFFER_MS:
            if data.get("access_token"):
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = data["access_token"]
            return

        refresh_token = data.get("refresh_token")
        if not refresh_token:
            return

        logger.info("Refreshing Claude OAuth token...")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": settings.claude_oauth_client_id,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                result = resp.json()

            new_access = result["access_token"]
            new_refresh = result["refresh_token"]
            expires_in = result.get("expires_in", 28800)

            _save({
                "access_token": new_access,
                "refresh_token": new_refresh,
                "expires_at": now_ms + expires_in * 1000,
            })
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = new_access
            logger.info("Claude token refreshed, expires in %d hours", expires_in // 3600)

        except Exception as e:
            logger.error("Failed to refresh Claude token: %s", e)
            if data.get("access_token"):
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = data["access_token"]
