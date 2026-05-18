# Глафира-РекрутёрЕвроМед

Telegram-бот: AI-рекрутёр на базе **Talantix GraphQL API** + **Claude CLI**.
Перенесено и сильно переработано из `Arkady/ArkadyJarvis` (там был
рекрутёр на Potok.io).

Перед изменением кода **обязательно** прочитай разделы «Talantix API:
особенности и грабли» и «Решения, которые легко откатить и сломать всё».

## Что делает

1. `/start` → одна кнопка «Глафира — рекрутёр».
2. Загружает ACTIVE-вакансии из Talantix, для каждой считает количество
   кандидатов на этапе воронки `TALANTIX_TARGET_STAGE` (по умолчанию `«ИИ»`).
3. Показывает только те вакансии, где есть кандидаты на этом этапе:
   `Performance-маркетолог (15)`.
4. Клик по вакансии → подсчёт «новых» (фамилия БЕЗ префикса `NN-`) и
   «обработанных» (с префиксом). Кнопки:
   - «✅ Оценить новых (N)»
   - «🔄 Переоценить всех (N)»
5. Цикл оценки:
   - дозагрузка полной карточки кандидата (резюме целиком в
     `StructuredResume.skills`),
   - Claude CLI оценивает 0–100 + breakdown по критериям + сильные/слабые
     стороны + 3–5 вопросов для контакта,
   - публикация HTML-комментария в Talantix (`createPersonComment`),
   - **безопасный** `editPerson`: префикс `NN-` к фамилии (`72-Пушной`),
     с сохранением всех остальных полей кандидата.

## Tech Stack

- **Python 3.11+**, aiogram v3 (polling), pydantic / pydantic-settings, httpx
- **AI**: Claude CLI (subscription, OAuth — `data/.claude_token.json`).
  Модель по умолчанию `claude-opus-4-7` (через `CLAUDE_MODEL` в `.env`).
- **Talantix GraphQL API** (`https://api.talantix.ru/graphql`)
  с авто-рефрешем токена через `https://api.talantix.ru/oauth/token`.
- **БЕЗ** FastAPI/HTTP-сервера — бот работает чистым long-polling.
- **БЕЗ** базы данных — состояние FSM в памяти aiogram, токены в JSON-файлах
  в `data/`.

## Project Structure

```
app/
  main.py                       # entry point: aiogram polling
  config.py                     # pydantic-settings (BOT_TOKEN, TALANTIX_*, CLAUDE_*, RECRUITER_ALLOWED)
  utils.py                      # parse_json_response (терпит markdown fences)
  version.py                    # __version__ (показывается в /start)
  bot/
    create.py                   # create_bot() + create_dispatcher() — регистрация роутеров
    routers/
      start.py                  # /start, главное меню (одна кнопка), HELLO_TEXT с версией
      recruiter.py              # FSM Recruiter: choosing_job → confirming → scoring; "новый/обработанный" по префиксу lastName
  services/
    ai_client.py                # Claude CLI wrapper (subprocess `claude --print`)
    claude_token.py             # Claude OAuth refresh (data/.claude_token.json), asyncio.Lock
    talantix_token.py           # Talantix OAuth refresh (data/.talantix_token.json), 401-fallback retry
    talantix_client.py          # GraphQL клиент: vacancies/persons/person + createPersonComment + safe editPerson
    talantix_models.py          # Pydantic-модели (Vacancy, Person, StructuredResume, ContactItem, ScoringResult)
    resume_scorer.py            # Промпт + score_person() — отдаёт ScoringResult с breakdown[].max_score
scripts/
  introspect.py                 # CLI для проверки Talantix-схемы (introspection отключён на сервере, но __type запросы можно)
tests/
  test_models.py
  test_score_prefix.py
  test_utils.py
Dockerfile, docker-compose.yml, .dockerignore, DEPLOY.md
```

## Логика бота (FSM)

`app/bot/routers/recruiter.py` — единственный workflow:

```
[/start] → MENU_KB
    ↓ click "Глафира — рекрутёр"
[Recruiter.choosing_job]
    показать список ACTIVE-вакансий с count кандидатов на этапе ИИ
    скрыть вакансии где count == 0 (если стадия задана в .env)
    ↓ click на вакансию
[Recruiter.confirming]
    разделить кандидатов на «новых» (нет префикса NN- в lastName) и «обработанных»
    показать кнопки «Оценить новых (N)» / «Переоценить всех (N)»
    ↓ click
[Recruiter.scoring]
    цикл по person_ids, для каждого:
        - get_person_full(id) → дозагружает резюме + contacts/citizenship/birthday
        - score_person(job, person, ai_client) → Claude CLI
        - push_scoring(result, person) → коммент + safe editPerson с префиксом
    кнопка «⏹ Остановить» останавливает цикл после текущего кандидата
```

«Обработанность» определяется регуляркой `^\d+-` в `lastName`. Префикс
формируется как `f"{score:02d}-{clean_last}"` (две цифры с ведущим нулём:
`02-Козлов`, `73-Козлов`).

## Talantix API: особенности и грабли

### Схема (выяснено эмпирическими probes — introspection заблокирован)

- `Vacancy` и `Person` — это **interfaces/unions**. Запросы делать через
  inline-фрагменты `... on VacancyItem`, `... on PersonItem`. `person(id)`
  может вернуть `PersonError` — это не GraphQL-ошибка, а часть union.
- `vacancies(first, after, sortBy, sortAsc)` → `Vacancies { items: [VacancyItem] }`.
  - `VacancyItem`: `id, title, status, department, description, url, createdAt`.
  - **Лимит first=200** на запрос. **Курсорной пагинации НЕТ** в нашей выборке
    полей — `endCursor`/`hasNextPage` отсутствуют. Достаточно для < 200 вакансий.
  - `VacancyFilterInput` НЕ имеет фильтра по статусу — фильтруем `ACTIVE` локально.
- `persons(first, after, filter)` → `{ items: [PersonItem], pageInfo { hasNextPage endCursor } }`.
  - `PersonFilterInput.vacancyIds: [Int!]` и `currentWfStatusNames: [String!]`
    — рабочие фильтры.
  - **Пагинация — стандартный Relay-cursor** (`pageInfo.endCursor` →
    следующий `after`, идём пока `hasNextPage=true`).
  - Сервер **жёстко капит на 50 элементов** за страницу независимо от
    запрошенного `first` (проверено: first=100/200/500/1000 — все по 50).
  - `total`/`totalCount` отсутствуют — общее число только перечислением.
  - `PersonItem`: `id, firstName, lastName, middleName, gender, updatedAt`,
    `area { id name }`, `contacts { items { ... on ContactItem { type value } } }`,
    `citizenships { items { ... on Area { id name } } }`,
    `tags { items { ... on PersonTag { id name } } }`,
    `resumes { items { ... on StructuredResume { id title skills } } }`.
- **`StructuredResume.skills`** — это **плоская строка целиком всё резюме**
  (опыт, навыки, образование, достижения). Не парсим, отдаём AI как есть.
- `birthDay` — `Instant` (timestamp ms), не строка.
- `gender` — enum lowercase: `male`, `female`. (`MALE`/`FEMALE` отвергает.)
- `contacts.type` — enum lowercase: `cell` (мобильный), `email`, `home`, `work`,
  `personal`, `skype`, `telegram`, `icq`, `linkedin`, `facebook`, `vk`.
  `phone`/`mobile`/`PHONE` НЕ работают.
- Talantix area IDs совпадают с hh.ru: Санкт-Петербург = `"2"`, Россия = `"113"`.
- Для GraphQL `editPerson` — поле `gender` и `contacts[].type` приходят
  как **EnumValue** (без кавычек). Pydantic/JSON через variables их не пропустит,
  поэтому собираем GraphQL-литерал руками: см. `_format_input_literal()`
  и класс-маркер `_GqlEnum`.

### Мутации (полный список 31, для нас критично)

- `createPersonComment(commentCreate: { personId, commentVisibility: { visibleForAll }, text })`
  → возвращает `Comment`. Поле текста — **`text`** (не `body`/`content`).
  Поддерживает HTML (`<strong>`, `<ul>`, `<li>`, `<code>`, `<p>`, `<h3>`).
  **НЕ поддерживает**: `<b>` (показывает буквы как обычные), `<table>`
  (рендерится одной строкой). См. `_build_comment_text()`.
- `editPerson(personEdit: PersonEditInput)` — **полная замена**: поля,
  не переданные в input, **обнуляются**. Знаменитый баг — у Пушного
  в первой версии бота пропали phone/email/birthday/citizenship/gender/area
  потому что мы их не передавали. Лечится через `safe_set_score_prefix`:
  предзагружаем кандидата через `get_person_full`, передаём ВСЕ поля
  обратно + меняем только `lastName`.
  - `PersonEditInput.contacts: [ContactInput]` — массив. Для одного
    контакта — массив длины 1.
  - `gender`, `contacts[].type` — enum (см. выше).
  - `areaId: String` (НЕ Int).
  - `citizenshipIds: [String]`.
  - `birthDay: Instant` (timestamp ms).
  - `source` (как объект input), `phones`, `email`, `birthday` (camelCase),
    `citizenship` — **отсутствуют** в `PersonEditInput`.
  - **`sourceId: Int`** — ЕСТЬ. Источник кандидата читается как
    `PersonItem { source { id name } }` (например, «Отклик, hh.ru»), при
    `editPerson` обязательно передавать обратно `sourceId: <int>`, иначе
    источник сбрасывается в null и в UI отображается «Не указан». Делает
    `safe_set_score_prefix`. До v0.3.7 этого не было — Глафира затирала
    источник у всех, кого префиксовала.
- `createPersonTag(personTagCreate: { personId, name })` → `PersonTag`.
  Идемпотентен (повторный create с тем же name не плодит дубль).
  **❗ Удалять теги через API НЕЛЬЗЯ** — нет `deletePersonTag/removePersonTag/...`
  ни в GraphQL, ни в REST (24 имени проверены, доки подтверждают).
  Поэтому **не используем теги вообще**, балл — только в комменте и в префиксе фамилии.

### Авторизация

- `Authorization: Bearer <access_token>`, `User-Agent: Глафира/N (контакт)`
  обязателен.
- `access_token` живёт 24 ч, `refresh_token` — 120 дней. Refresh через
  `POST https://api.talantix.ru/oauth/token` с
  `grant_type=refresh_token&refresh_token=<X>` (БЕЗ client_id/secret).
- Refresh-токены **одноразовые** — после успешного обновления старый
  становится невалидным. Поэтому актуальная пара живёт в
  `data/.talantix_token.json` (НЕ в `.env`). На клиенте есть
  `force_refresh_on_401()` для retry при 401.

## Решения, которые легко откатить и сломать всё

### 1. Никогда НЕ используй `editPerson` без полного набора полей

Это полная замена. Минимальный safe-набор:
`id, firstName, lastName, middleName?, gender?, areaId?, birthDay?,
citizenshipIds?, sourceId?, contacts?`.
**`sourceId` обязательно передавать**, иначе источник «Отклик, hh.ru» и
любой другой сбрасывается в null. Источник предзагружается из
`PersonItem { source { id name } }` в `get_person_full`.
Используй `TalantixClient.safe_set_score_prefix(person, score)` —
он делает это правильно.

### 2. НЕ ставь теги с цифрой балла (например `AI: 72`)

Удалить их API не даёт. При rescore в карточке накопится мусор:
`AI: 72`, `AI: 65`, `AI: 80`. Мы убрали теги совсем — обработанность
определяется по префиксу `NN-` в фамилии.

### 3. HTML-комментарии: что работает в Talantix

| Что | Работает? |
|-----|-----------|
| `<h3>`, `<p>`, `<br>` | ✅ |
| `<ul>`/`<li>` | ✅ |
| `<strong>` | ✅ |
| `<code>` (моноширинный) | ✅ |
| `<b>` | ❌ (буквы остаются обычными) |
| `<table>` | ❌ (рендерится одной строкой) |
| `**markdown**` | ❌ |

### 4. Сборка Docker и симлинки

В `.dockerignore` обязательно исключи `data` (без слеша). Иначе на проде,
где `data` симлинк на `~/ArkadyJarvis/data`, при `COPY . .` в образ попадёт
broken-симлинк и `mkdir -p /app/data` упадёт «File exists».

### 5. Общий `data/` с ArkadyJarvis

На проде `data/` — это симлинк на `~/ArkadyJarvis/data`. Зачем:
**Claude refresh-токен одноразовый**. Если ArkadyJarvis и Глафира хранят
`.claude_token.json` отдельно, при ротации одного бота токен другого
становится невалидным. Общий файл = один источник правды.

`data/.talantix_token.json` — наш собственный, у Arkady нет.

## AI-скоринг (resume_scorer.py)

Промпт собирается из:
- `job.title`, `job.department`, `job.description` (HTML — отдаём как есть,
  AI игнорирует теги).
- `person.display_name`, `person.area.name`, `resume_title` и
  `resume_text` (это `StructuredResume.skills` — плоский текст всего резюме).
- Извлечённые «инструкции рекрутёра» из описания вакансии: всё что после
  строки `Важно для CLAUDE:` идёт отдельным блоком в промпт.

AI возвращает строгий JSON:
```json
{
  "score": 0-100,
  "reasoning": "...",
  "breakdown": [
    {"criterion": "...", "score": N, "max_score": M, "comment": "..."}
  ],
  "strengths": [...],
  "weaknesses": [...],
  "questions": [...]
}
```

Сумма `max_score` по всем критериям = 100 (зашито в промпт).
Парсим через `parse_json_response()` (терпим markdown fences и текст
вокруг JSON).

## Конфигурация (`.env`)

```env
BOT_TOKEN=                           # обязательно
TALANTIX_API_TOKEN=                  # обязательно (seed; обновляется автоматически)
TALANTIX_REFRESH_TOKEN=              # обязательно (seed)
TALANTIX_BASE_URL=https://api.talantix.ru/graphql
TALANTIX_USER_AGENT=Глафира/0.3 (contact@example.ru)
TALANTIX_TARGET_STAGE=ИИ             # имя этапа воронки. Пусто = брать всех.
CLAUDE_CLI_PATH=claude
CLAUDE_MODEL=claude-opus-4-7
CLAUDE_CODE_OAUTH_TOKEN=             # seed для контейнера (на маке не нужен)
CLAUDE_REFRESH_TOKEN=
CLAUDE_OAUTH_CLIENT_ID=9d1c250a-e61b-44d9-88ed-5944d1962f5e
RECRUITER_ALLOWED=                   # пусто = открытый бот
```

## Деплой

См. `DEPLOY.md`. Кратко:
```bash
git clone https://github.com/artemsitnikoff/glafiraeuro.git
cd glafiraeuro && cp .env.example .env && nano .env
rm -rf data && ln -s ~/ArkadyJarvis/data ./data    # общий data
docker compose up -d --build
```

Обновление:
```bash
cd ~/glafiraeuro && git pull && docker compose up -d --build
```

## Версионирование

`app/version.py` → `__version__`. Показывается в `/start` (`v0.3.5`).
Бамп при каждом изменении бота. Patch — фиксы и UX, minor — фичи или
архитектурные сдвиги (тег→префикс, плоский text→HTML).

## Тесты

```bash
.venv/bin/pytest -q
```

15 юнит-тестов: модели, парсер JSON, формат префикса. Юнит-тесты не
ходят в Talantix — для интеграционной проверки используй
`scripts/introspect.py` или короткий smoke-скрипт через
`TalantixClient`.

## Ссылки

- **Repo**: https://github.com/artemsitnikoff/glafiraeuro
- **Talantix API docs**: https://api.talantix.ru/docs/
- **Talantix UI**: https://talantix.ru/ats
- **Telegram bot**: `@glafirahr_euro_bot`
