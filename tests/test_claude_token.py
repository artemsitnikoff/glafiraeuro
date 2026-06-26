"""Статический режим Claude-токена (long-lived sk-ant-oat01 без рефреша).

Развязка с общим data/.claude_token.json: при заданном CLAUDE_CODE_OAUTH_TOKEN
и пустом CLAUDE_REFRESH_TOKEN берём токен из env, файл/рефреш не трогаем.
"""

import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "test")

from app.config import settings  # noqa: E402
from app.services import claude_token  # noqa: E402


def test_static_token_active(monkeypatch):
    monkeypatch.setattr(settings, "claude_code_oauth_token", "sk-ant-oat01-LIVE")
    monkeypatch.setattr(settings, "claude_refresh_token", "")
    assert claude_token._static_token() == "sk-ant-oat01-LIVE"


def test_static_token_disabled_when_refresh_present(monkeypatch):
    # Есть refresh → НЕ статрежим (используется старый путь с файлом/рефрешем)
    monkeypatch.setattr(settings, "claude_code_oauth_token", "sk-ant-oat01-LIVE")
    monkeypatch.setattr(settings, "claude_refresh_token", "refresh-xyz")
    assert claude_token._static_token() is None


def test_static_token_none_without_oauth(monkeypatch):
    monkeypatch.setattr(settings, "claude_code_oauth_token", "")
    monkeypatch.setattr(settings, "claude_refresh_token", "")
    assert claude_token._static_token() is None


def test_ensure_fresh_token_static_sets_env_and_skips_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "claude_code_oauth_token", "sk-ant-oat01-Z")
    monkeypatch.setattr(settings, "claude_refresh_token", "")
    # Подменяем путь файла на временный — он не должен ни читаться, ни создаваться
    fake_file = tmp_path / ".claude_token.json"
    monkeypatch.setattr(claude_token, "TOKEN_FILE", fake_file)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    asyncio.run(claude_token.ensure_fresh_token())

    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-Z"
    assert not fake_file.exists()


def test_init_token_file_static_sets_env_and_skips_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "claude_code_oauth_token", "sk-ant-oat01-INIT")
    monkeypatch.setattr(settings, "claude_refresh_token", "")
    fake_file = tmp_path / ".claude_token.json"
    monkeypatch.setattr(claude_token, "TOKEN_FILE", fake_file)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    claude_token.init_token_file()

    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-INIT"
    assert not fake_file.exists()
