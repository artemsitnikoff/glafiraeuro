"""Авто-рефреш Talantix OAuth токена.

Хранит access + refresh токены в data/.talantix_token.json. refresh_token
ротируется при каждом запросе к /oauth/token (одноразовый — старый
становится недействительным после успешного обновления).

При первом запуске seed-токены берутся из .env. Дальше всё хранится в
файле, чтобы последовательные перезапуски бота не теряли свежий
refresh_token (старый из .env уже невалидный после первого refresh).
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

TOKEN_FILE = Path("data/.talantix_token.json")
TOKEN_URL = "https://api.talantix.ru/oauth/token"
# Рефрешим за 10 минут до окончания срока (срок access_token ≈ 24 часа)
REFRESH_BUFFER_MS = 600_000

_lock = asyncio.Lock()


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


def init_from_env() -> None:
    """Если файла нет — заполнить его seed-значениями из .env."""
    if TOKEN_FILE.exists() and _load().get("refresh_token"):
        return

    access = settings.talantix_api_token.get_secret_value()
    refresh = settings.talantix_refresh_token
    if not access and not refresh:
        return

    _save({
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": 0,  # форсируем refresh при первом использовании
    })
    logger.info("Talantix token file initialized from env")


async def _refresh() -> str:
    data = _load()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        # Нет refresh — отдаём что есть; пусть GraphQL вернёт 401
        return data.get("access_token") or settings.talantix_api_token.get_secret_value()

    logger.info("Talantix: refreshing access token via /oauth/token")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()

    new_access = body["access_token"]
    new_refresh = body["refresh_token"]
    expires_in = int(body.get("expires_in", 86400))
    _save({
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_at": time.time() * 1000 + expires_in * 1000,
    })
    logger.info("Talantix: token refreshed, expires in %dh", expires_in // 3600)
    return new_access


async def get_access_token() -> str:
    """Свежий access_token. Авто-рефреш если истекает."""
    async with _lock:
        data = _load()
        now_ms = time.time() * 1000
        if data.get("expires_at", 0) > now_ms + REFRESH_BUFFER_MS and data.get("access_token"):
            return data["access_token"]

        # Время рефрешить или впервые поднимаем
        if not data:
            init_from_env()
            data = _load()
            if data.get("expires_at", 0) > now_ms + REFRESH_BUFFER_MS:
                return data["access_token"]

        try:
            return await _refresh()
        except Exception as e:
            logger.error("Talantix refresh failed: %s", e)
            # Возвращаем последний известный access (может уже истёк — и пусть)
            return data.get("access_token") or settings.talantix_api_token.get_secret_value()


async def force_refresh_on_401() -> str:
    """Принудительный refresh при получении 401 от GraphQL — на случай, если
    мы локально считаем токен живым, но сервер уже забраковал."""
    async with _lock:
        try:
            return await _refresh()
        except Exception as e:
            logger.error("Talantix forced refresh failed: %s", e)
            return _load().get("access_token", "")
