# Глафира-РекрутерЕвромед

Telegram-бот: AI-рекрутёр на базе Talantix + Claude CLI.

Перенесено из `Arkady/ArkadyJarvis` (рекрутёр на Potok.io) с заменой
интеграции на **Talantix GraphQL API**.

## Что делает

1. `/start` → одна кнопка «Глафира — рекрутёр».
2. Загружает список вакансий из Talantix с количеством кандидатов в скобках:
   `Бэкенд-разработчик (12)`.
3. По клику на вакансию: считает кандидатов на этапе
   `TALANTIX_TARGET_STAGE` (по умолчанию «ИИ») и делит на:
   - **новых** — у кого фамилия не начинается с префикса `NNN-`
   - **обработанных** — у кого префикс уже есть
4. Кнопки:
   - «✅ Оценить новых (N)»
   - «🔄 Переоценить всех (N)»
5. По каждому кандидату:
   - дозагружает резюме через `person(id)`,
   - просит Claude CLI оценить от 0 до 100 + дать разбивку, сильные/слабые
     стороны и 3–5 вопросов для контакта,
   - публикует HTML-комментарий через `createPersonComment`,
   - дописывает балл префиксом к фамилии: `editPerson(lastName: "085-Иванов")`.

Балл к ФИО плюсуется → в Talantix кандидаты сортируются по фамилии и
сильные сразу всплывают наверх.

## Установка

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# заполнить BOT_TOKEN, TALANTIX_API_TOKEN, CLAUDE_*
```

## Запуск

```sh
.venv/bin/python -m app.main
```

## Тесты

```sh
.venv/bin/pytest -q
```

## Проверка GraphQL-схемы Talantix

Если поля в `talantix_client.py` отличаются от реальной схемы (имена
типа `candidatesCount`, `workflowStatistics`, `aboutMe` могут не
совпасть), используй интроспекцию:

```sh
.venv/bin/python scripts/introspect.py Vacancy
.venv/bin/python scripts/introspect.py Person
.venv/bin/python scripts/introspect.py PersonResume
.venv/bin/python scripts/introspect.py PersonFilterInput
.venv/bin/python scripts/introspect.py --query vacancies
```

После этого правь GraphQL-запросы (`VACANCIES_QUERY`, `PERSON_QUERY`,
…) в `app/services/talantix_client.py` под реальные имена полей.

## Структура

```
app/
├── config.py                 # pydantic-settings из .env
├── main.py                   # точка входа: aiogram polling
├── utils.py                  # parse_json_response
├── bot/
│   ├── create.py             # bot, dispatcher
│   └── routers/
│       ├── start.py          # /start, главное меню
│       └── recruiter.py      # FSM: вакансии → оценка
└── services/
    ├── ai_client.py          # Claude CLI wrapper
    ├── claude_token.py       # OAuth refresh
    ├── talantix_client.py    # GraphQL клиент Talantix
    ├── talantix_models.py    # Pydantic модели ответов
    └── resume_scorer.py      # промпт + score_person()
scripts/
└── introspect.py             # проверить схему Talantix
tests/
├── test_models.py
├── test_score_prefix.py
└── test_utils.py
```

## Что было выкинуто из ArkadyJarvis

- FastAPI обёртка, scheduler, вебхуки.
- Bitrix24, Jira, OpenRouter, OpenClaw, Telethon-userbot.
- Стадии «Интервью с рекрутером» / «Интервью с менеджером», авто-приглашения,
  обмен сообщениями с кандидатом — мы оставили только цикл
  «вакансия → новые → оценить → комментарий + префикс».

## Известные допущения по Talantix API

Документация Talantix не показывает полную схему публично, поэтому
GraphQL-запросы построены на типичных именах полей (`candidatesCount`,
`workflowStatistics`, `keySkills`, `area`, `currentWorkflowStatus`,
`resume.aboutMe` и т.п.). При первом запуске:

1. Если `vacancies`/`persons` падают с GraphQL-ошибкой про неизвестное
   поле — запусти `scripts/introspect.py <TypeName>` и подправь
   соответствующий блок запроса в `app/services/talantix_client.py`.
2. Pydantic-модели уже допускают неизвестные поля (`extra='allow'`),
   так что лишние данные от Talantix ничего не сломают.
