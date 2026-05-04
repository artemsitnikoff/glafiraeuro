# Деплой Глафиры-РекрутёрЕвроМед

## Требования к серверу

- Docker + Docker Compose
- Git
- Сетевой доступ к `api.talantix.ru` и `api.anthropic.com`

## Первоначальная установка

### 1. Клонировать репозиторий

```bash
git clone <git-url-проекта> glafiraeuro
cd glafiraeuro
```

### 2. Настроить `.env`

```bash
cp .env.example .env
nano .env
```

Заполнить обязательные:
- `BOT_TOKEN` — токен бота от BotFather
- `TALANTIX_API_TOKEN` — access_token Talantix (живёт 24 ч; обновится сам через refresh)
- `TALANTIX_REFRESH_TOKEN` — refresh_token Talantix (живёт 120 дней)
- `TALANTIX_USER_AGENT` — `Глафира/N (контакт)` — Talantix требует
- `TALANTIX_TARGET_STAGE` — этап воронки, по которому отбираем кандидатов (`ИИ`)
- `CLAUDE_CODE_OAUTH_TOKEN` + `CLAUDE_REFRESH_TOKEN` — для Claude CLI в контейнере
- `RECRUITER_ALLOWED` — `,`-разделённый список Telegram-id с доступом (или пусто = открытый бот)

### 3. Подключить общий `data/` через симлинк на ArkadyJarvis

⚠️ **Важно:** Claude OAuth refresh-токены **одноразовые** — при ротации старый
становится невалидным. Если ArkadyJarvis и Глафира хранят `.claude_token.json`
в разных файлах, они перетирают друг друга и оба бота падают с 401.

Делаем общий `data/` через симлинк:

```bash
# из директории проекта
rm -rf data
ln -s ~/ArkadyJarvis/data ./data
ls -la data
# должно показать: data -> /home/user/ArkadyJarvis/data
```

В общей папке `data/` лежат:
- `.talantix_token.json` — токены Talantix (только наши, у Arkady нет конфликта)
- `.claude_token.json` — токены Claude OAuth (общие на оба бота)

Docker через `./data:/app/data` корректно следует за симлинком — контейнер видит реальные файлы из `~/ArkadyJarvis/data/`.

### 4. Запустить

```bash
docker compose up -d --build
docker compose logs -f
```

Должно появиться:
```
[INFO] glafira: Glafira bot polling started
[INFO] aiogram.dispatcher: Run polling for bot @glafirahr_euro_bot
```

## Обновление (новая версия)

```bash
cd ~/glafiraeuro
git pull
docker compose up -d --build
```

Одной строкой:
```bash
cd ~/glafiraeuro && git pull && docker compose up -d --build
```

### Проверка после обновления

```bash
docker compose logs --tail=50
docker compose ps
```

В `/start` бот покажет текущую версию (например `v0.3.2`).

## Полезные команды

```bash
docker compose logs -f          # логи в реальном времени
docker compose restart          # рестарт без пересборки
docker compose down             # остановить
docker compose up -d --build    # пересобрать и запустить
docker compose exec bot bash    # зайти в контейнер
docker compose exec bot python -c "from app.version import __version__; print(__version__)"
```

## Бэкап и миграция

В `data/` хранится только пара актуальных токенов — бэкап делать смысла мало
(всегда можно обновить токены). Если переезжаешь на новый сервер:

```bash
# на старом сервере
scp data/.talantix_token.json data/.claude_token.json user@new:~/glafiraeuro/data/
```

## Структура `data/`

```
data/
  .talantix_token.json   # Talantix OAuth (ротируется при rate-limit ≈ 24ч)
  .claude_token.json     # Claude OAuth (рефреш 8ч)
```

Оба файла персистентны через docker volume `./data:/app/data`. При `docker compose down` сохраняются.

## Особенности

- **Нет HTTP-сервера** — бот общается с Telegram через polling, портов наружу не открывает.
- **Claude CLI в контейнере** — устанавливается из `npm @anthropic-ai/claude-code`. Авторизуется через переменные `CLAUDE_CODE_OAUTH_TOKEN` + `CLAUDE_REFRESH_TOKEN` (модуль `app.services.claude_token` сам их подкладывает в `data/.claude_token.json` и обновляет через `https://api.anthropic.com/v1/oauth/token`).
- **Talantix-токен** — `TALANTIX_API_TOKEN` живёт 24 часа, но `TALANTIX_REFRESH_TOKEN` обновляется автоматически через `https://api.talantix.ru/oauth/token`. После первого refresh реальный refresh-токен живёт в `data/.talantix_token.json` (одноразовый — при ротации старый из `.env` становится невалидным; брать обновлённый из файла, если переезжать на новую машину).
