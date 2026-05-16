"""Клиент Talantix GraphQL — реальная схема, проверенная на api.talantix.ru.

Особенности:
* Типы Vacancy и Person — interfaces (union с *Error). Запросы делаем через
  inline-фрагмент `... on VacancyItem`, `... on PersonItem`.
* В резюме всё содержимое лежит плоской строкой в `StructuredResume.skills`
  (включая опыт работы, навыки, образование, достижения).
* `editPerson` требует `firstName` обязательно; шлём существующее.
* `createPersonComment` принимает `commentCreate: { personId, commentVisibility: { visibleForAll }, text }`.
* Пагинация `persons` — стандартный Relay-cursor: `pageInfo { hasNextPage endCursor }`.
  Сервер капит на 50 элементов за страницу независимо от `first` (проверено
  на проде: first=100/200/500/1000 — все возвращают по 50).
  Поля `total`/`totalCount` отсутствуют — общее кол-во считаем перечислением.
"""

import asyncio
import html as html_mod
import json
import logging
import re

import httpx

from app.config import settings
from app.services import talantix_token
from app.services.talantix_models import (
    Person,
    ScoringResult,
    Vacancy,
)

logger = logging.getLogger("glafira")


class _GqlEnum(str):
    """Маркер: при сериализации в GraphQL-литерал — без кавычек."""
    pass


def _extract_tag_names(node: dict) -> list[str]:
    tags = node.get("tags") or {}
    items = tags.get("items") or []
    return [t["name"] for t in items if t and t.get("name")]


def score_label(score: int) -> str:
    if score >= 81:
        return "Отлично"
    if score >= 61:
        return "Хорошо"
    if score >= 41:
        return "Средне"
    return "Слабо"


def _build_comment_text(result: ScoringResult) -> str:
    """HTML-комментарий для Talantix (поле text). Talantix принимает HTML
    и отображает его форматирование в карточке кандидата.
    """
    esc = html_mod.escape
    label = score_label(result.score)

    breakdown_html = ""
    if result.breakdown:
        # Все баллы выровнены слева в один столбец: формат "NN/NN" жирным,
        # с padding через &nbsp; до длины самой широкой записи
        # (всегда моноширинно через <code>).
        score_strs = [
            f"{b.score}/{b.max_score or 100}" for b in result.breakdown
        ]
        max_w = max(len(s) for s in score_strs)
        rows = ""
        for b, s in zip(result.breakdown, score_strs):
            pad = "&nbsp;" * (max_w - len(s))
            comment = f" — {esc(b.comment)}" if b.comment else ""
            rows += (
                f"<strong><code>{pad}{s}</code></strong> "
                f"{esc(b.criterion)}{comment}<br>"
            )
        breakdown_html = (
            f"<p><strong>📊 Разбивка по критериям:</strong></p>"
            f"<p>{rows}</p>"
            f"<p><strong>ИТОГО: {result.score}/100</strong></p>"
        )

    strengths = (
        "".join(f"<li>{esc(s)}</li>" for s in result.strengths)
        if result.strengths else "<li>—</li>"
    )
    weaknesses = (
        "".join(f"<li>{esc(s)}</li>" for s in result.weaknesses)
        if result.weaknesses else "<li>—</li>"
    )

    questions_html = ""
    if result.questions:
        items = "".join(f"<li>{esc(q)}</li>" for q in result.questions)
        marker = json.dumps(result.questions, ensure_ascii=False)
        questions_html = (
            f"<!--GLAFIRA:Q={marker}-->"
            f"<p><strong>💬 ВОПРОСЫ ДЛЯ ПЕРВОГО КОНТАКТА:</strong></p>"
            f"<ul>{items}</ul>"
        )

    return (
        f"<h3>🤖 Оценка AI: <strong>{result.score}/100</strong> ({label})</h3>"
        f"<p>{esc(result.reasoning)}</p>"
        f"{breakdown_html}"
        f"<p><strong>✅ СИЛЬНЫЕ СТОРОНЫ:</strong></p>"
        f"<ul>{strengths}</ul>"
        f"<p><strong>⚠️ СЛАБЫЕ СТОРОНЫ:</strong></p>"
        f"<ul>{weaknesses}</ul>"
        f"{questions_html}"
    )


# ---------- GraphQL запросы (имена полей подтверждены) ----------

VACANCIES_QUERY = """
query Vacancies($first: Int!, $after: String) {
  vacancies(first: $first, after: $after, sortBy: NAME, sortAsc: true) {
    items {
      ... on VacancyItem {
        id
        title
        status
        department
      }
    }
  }
}
""".strip()


VACANCY_QUERY = """
query Vacancy($id: Int!) {
  vacancy(id: $id) {
    ... on VacancyItem {
      id
      title
      status
      department
      description
      url
      createdAt
    }
  }
}
""".strip()


PERSONS_QUERY = """
query Persons($first: Int!, $after: String, $filter: PersonFilterInput) {
  persons(first: $first, after: $after, filter: $filter) {
    items {
      ... on PersonItem {
        id
        firstName
        lastName
        middleName
        updatedAt
        tags {
          items {
            ... on PersonTag { id name }
          }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()


PERSONS_COUNT_QUERY = """
query PersonsCount($first: Int!, $after: String, $filter: PersonFilterInput) {
  persons(first: $first, after: $after, filter: $filter) {
    items { ... on PersonItem { id } }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()


PERSON_QUERY = """
query Person($id: Int!) {
  person(id: $id) {
    __typename
    ... on PersonItem {
      id
      firstName
      lastName
      middleName
      gender
      birthDay
      area { id name }
      contacts { items { ... on ContactItem { type value } } }
      citizenships { items { ... on Area { id name } } }
      tags { items { ... on PersonTag { id name } } }
      resumes {
        items {
          ... on StructuredResume {
            id
            title
            skills
          }
        }
      }
    }
    ... on PersonError {
      message
    }
  }
}
""".strip()


CREATE_COMMENT_MUTATION = """
mutation CreatePersonComment($input: PersonCommentCreateInput!) {
  createPersonComment(commentCreate: $input) {
    __typename
    ... on Comment { id }
  }
}
""".strip()


CREATE_TAG_MUTATION = """
mutation CreatePersonTag($input: PersonTagCreateInput!) {
  createPersonTag(personTagCreate: $input) {
    __typename
    ... on PersonTag { id name }
  }
}
""".strip()


EDIT_PERSON_MUTATION = """
mutation EditPerson($input: PersonEditInput!) {
  editPerson(personEdit: $input) {
    __typename
    ... on PersonItem { id firstName lastName }
  }
}
""".strip()


# ---------- Клиент ----------


class TalantixError(Exception):
    pass


class TalantixClient:
    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.talantix_base_url,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": settings.talantix_user_agent,
            },
        )
        # Кап на параллельные запросы — сервер может ругаться при шквале
        self._sem = asyncio.Semaphore(8)

    async def close(self):
        await self._client.aclose()

    async def _gql(self, query: str, variables: dict | None = None, _retry: bool = True) -> dict:
        token = await talantix_token.get_access_token()
        async with self._sem:
            resp = await self._client.post(
                "",
                json={"query": query, "variables": variables or {}},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code == 401 and _retry:
            logger.info("Talantix 401 → forced refresh & retry")
            await talantix_token.force_refresh_on_401()
            return await self._gql(query, variables, _retry=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            msg = "; ".join(e.get("message", "?") for e in data["errors"])
            raise TalantixError(f"GraphQL: {msg}")
        return data.get("data") or {}

    # ----- Vacancies -----

    async def get_active_vacancies(self) -> list[Vacancy]:
        """ACTIVE-вакансии. Talantix возвращает на первой странице до 200
        записей (включая ARCHIVE), `VacancyFilterInput` фильтрации по статусу
        не имеет — отфильтруем локально. Если у клиента когда-нибудь станет
        больше 200 общих вакансий с активными за пределами первой страницы,
        нужна будет курсорная пагинация (формат `after` пока не известен).
        """
        result: list[Vacancy] = []
        data = await self._gql(VACANCIES_QUERY, {"first": 200, "after": None})
        items = ((data.get("vacancies") or {}).get("items")) or []
        for it in items:
            if not it:
                continue
            v = Vacancy.model_validate(it)
            if v.is_active:
                result.append(v)
        return result

    async def get_vacancy(self, vacancy_id: int) -> Vacancy:
        data = await self._gql(VACANCY_QUERY, {"id": vacancy_id})
        node = data.get("vacancy")
        if not node:
            raise TalantixError(f"Vacancy {vacancy_id} not found")
        return Vacancy.model_validate(node)

    # ----- Persons -----

    async def get_persons_for_vacancy(
        self,
        vacancy_id: int,
        stage_name: str | None = None,
        max_pages: int = 100,
    ) -> list[Person]:
        """Кандидаты вакансии (опц. отфильтровано по этапу).

        Сервер капит на 50 за страницу. Идём по `pageInfo.endCursor` пока
        `hasNextPage=true`. `max_pages` — страховка от бесконечного цикла
        (100 страниц = 5000 кандидатов).
        """
        filter_: dict = {"vacancyIds": [vacancy_id]}
        if stage_name:
            filter_["currentWfStatusNames"] = [stage_name]

        results: list[Person] = []
        cursor: str | None = None
        for _ in range(max_pages):
            data = await self._gql(
                PERSONS_QUERY,
                {"first": 50, "after": cursor, "filter": filter_},
            )
            persons_obj = data.get("persons") or {}
            items = persons_obj.get("items") or []
            for it in items:
                if not it:
                    continue
                tag_names = _extract_tag_names(it)
                results.append(Person.model_validate({**it, "tag_names": tag_names}))
            page_info = persons_obj.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break
        else:
            logger.warning(
                "Talantix: vacancy %s этап '%s' — упёрлись в max_pages=%d, "
                "собрано %d кандидатов; возможно есть ещё",
                vacancy_id, stage_name, max_pages, len(results),
            )
        return results

    async def count_persons_for_vacancy(
        self,
        vacancy_id: int,
        stage_name: str | None = None,
        max_pages: int = 100,
    ) -> int:
        """Кол-во кандидатов по фильтру. Лёгкий ID-only запрос с курсорной
        пагинацией — честный int без «50+» хака."""
        filter_: dict = {"vacancyIds": [vacancy_id]}
        if stage_name:
            filter_["currentWfStatusNames"] = [stage_name]

        total = 0
        cursor: str | None = None
        for _ in range(max_pages):
            data = await self._gql(
                PERSONS_COUNT_QUERY,
                {"first": 50, "after": cursor, "filter": filter_},
            )
            persons_obj = data.get("persons") or {}
            items = persons_obj.get("items") or []
            total += sum(1 for it in items if it)
            page_info = persons_obj.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break
        else:
            logger.warning(
                "Talantix: count vacancy %s этап '%s' — упёрлись в max_pages=%d",
                vacancy_id, stage_name, max_pages,
            )
        return total

    async def get_person_full(self, person_id: int) -> Person:
        """Полная карточка с резюме. Если PersonError — возвращаем заглушку
        с теми полями, что были."""
        data = await self._gql(PERSON_QUERY, {"id": person_id})
        node = data.get("person") or {}
        typename = node.get("__typename")
        if typename == "PersonError":
            raise TalantixError(f"Person {person_id}: {node.get('message')}")

        # Извлечь текст резюме
        resume_text = None
        resume_title = None
        resumes = (node.get("resumes") or {}).get("items") or []
        if resumes:
            r = resumes[0] or {}
            resume_text = r.get("skills")
            resume_title = r.get("title")

        # Извлечь contacts и citizenships для безопасного editPerson
        contacts = ((node.get("contacts") or {}).get("items")) or []
        citizenships = ((node.get("citizenships") or {}).get("items")) or []
        citizenship_ids = [c["id"] for c in citizenships if c and c.get("id")]

        return Person.model_validate({
            **node,
            "tag_names": _extract_tag_names(node),
            "contacts_list": [c for c in contacts if c],
            "citizenship_ids": citizenship_ids,
            "resume_text": resume_text,
            "resume_title": resume_title,
        })

    # ----- Безопасный editPerson -----

    async def safe_set_score_prefix(self, person: Person, score: int) -> None:
        """Поставить префикс `NN-` к фамилии БЕЗ потери данных.

        editPerson в Talantix ведёт себя как полная замена: поля, не
        переданные в input, обнуляются. Поэтому передаём ВСЕ поля, что
        прочитали в `person`, и меняем только lastName.

        Префикс — 2 цифры с ведущим нулём для `score < 10`: «73-Козлов»,
        «02-Козлов».
        """
        if person.lastName is None:
            logger.warning("safe_set_score_prefix: person %s has no lastName", person.id)
            return

        clean_last = re.sub(r"^\d+-", "", person.lastName).strip() or person.lastName
        new_last = f"{score:02d}-{clean_last}"

        edit_input: dict = {
            "id": person.id,
            "firstName": person.firstName or "",
            "lastName": new_last,
        }
        if person.middleName:
            edit_input["middleName"] = person.middleName
        if person.gender in ("male", "female"):
            edit_input["gender"] = _GqlEnum(person.gender)
        if person.area and person.area.id is not None:
            edit_input["areaId"] = str(person.area.id)
        if person.birthDay:
            edit_input["birthDay"] = int(person.birthDay)
        if person.citizenship_ids:
            edit_input["citizenshipIds"] = list(person.citizenship_ids)
        if person.contacts_list:
            edit_input["contacts"] = [
                {"type": _GqlEnum(c.type), "value": c.value}
                for c in person.contacts_list
                if c.type and c.value
            ]

        literal = self._format_input_literal(edit_input)
        query = (
            "mutation EditPerson { "
            f"editPerson(personEdit: {literal}) {{ "
            "__typename ... on PersonItem { id lastName } "
            "} "
            "}"
        )
        await self._gql(query)

    @staticmethod
    def _format_input_literal(value) -> str:
        """Сериализовать dict/list в GraphQL-литерал (без кавычек у ключей).
        `_GqlEnum` сериализуется без кавычек (для enum-значений GraphQL).
        """
        if isinstance(value, _GqlEnum):
            return str(value)
        if isinstance(value, dict):
            parts = [
                f"{k}: {TalantixClient._format_input_literal(v)}"
                for k, v in value.items()
            ]
            return "{ " + ", ".join(parts) + " }"
        if isinstance(value, list):
            return "[" + ", ".join(
                TalantixClient._format_input_literal(v) for v in value
            ) + "]"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(str(value), ensure_ascii=False)

    # ----- Mutations -----

    async def create_comment(self, person_id: int, text: str, visible_for_all: bool = True) -> None:
        await self._gql(
            CREATE_COMMENT_MUTATION,
            {"input": {
                "personId": person_id,
                "commentVisibility": {"visibleForAll": visible_for_all},
                "text": text,
            }},
        )

    async def add_tag(self, person_id: int, name: str) -> None:
        """Создать тег у кандидата. Talantix идемпотентен — повторный вызов
        с тем же именем не создаёт дубликата."""
        await self._gql(
            CREATE_TAG_MUTATION,
            {"input": {"personId": person_id, "name": name}},
        )

    # ----- Высокоуровневая операция -----

    async def push_scoring(self, result: ScoringResult, person: Person | None = None) -> None:
        """Опубликовать оценку: коммент + префикс `NN-` к фамилии.

        Если передан `person` — ставим префикс к фамилии безопасно
        (передаём ВСЕ поля кандидата, чтобы editPerson не обнулил их).
        Без `person` префикс не ставим.

        Теги не используем: Talantix API не даёт мутации для удаления
        тегов, и при rescore у кандидата накапливался бы мусор.
        Признак «обработан» — префикс `NN-` в фамилии.
        """
        comment = _build_comment_text(result)
        await self.create_comment(result.person_id, comment, visible_for_all=True)

        if person is not None:
            try:
                await self.safe_set_score_prefix(person, result.score)
            except Exception as e:
                logger.warning(
                    "Talantix: comment posted for person %s (score %d) but "
                    "failed to set score prefix on lastName: %s",
                    result.person_id, result.score, e,
                )


# Маркер «оценено AI» — единый тег, без балла. Идемпотентно при rescore
# (Talantix не даёт мутации для удаления тегов, поэтому балл в теге
# плодил бы мусор: "AI: 72", "AI: 85", ... — теперь один тег "AI").
# Старые теги вида "AI: NN" продолжаем считать признаком обработки —
# просто не создаём новых таких.
SCORE_TAG_NAME = "AI"


def format_score_tag(score: int) -> str:
    return SCORE_TAG_NAME


def is_score_tag(name: str) -> bool:
    if not name:
        return False
    return name == SCORE_TAG_NAME or name.startswith("AI: ")
