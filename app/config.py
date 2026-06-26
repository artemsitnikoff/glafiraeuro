from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: SecretStr

    # Talantix
    talantix_api_token: SecretStr = SecretStr("")
    talantix_refresh_token: str = ""
    talantix_base_url: str = "https://api.talantix.ru/graphql"
    talantix_user_agent: str = "GlafiraEuromed/0.1 (artem.sitnikoff@gmail.com)"
    # Имя этапа воронки в Talantix, по которому отбираем кандидатов.
    # Пусто = берём всех кандидатов вакансии.
    talantix_target_stage: str = "ИИ"

    # Claude CLI (как в Arkady)
    claude_cli_path: str = "claude"
    claude_model: str = ""
    claude_code_oauth_token: str = ""
    claude_refresh_token: str = ""
    claude_oauth_client_id: str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

    # Access control: comma-separated telegram IDs. Пусто = открытый бот.
    recruiter_allowed: str = ""

    # extra="ignore": .env шарится с ArkadyJarvis и может содержать чужие
    # переменные (напр. CLAUDE_TOKEN_FILE) — Глафире они не нужны, но без
    # ignore pydantic падает на «extra_forbidden» ещё до старта бота.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
