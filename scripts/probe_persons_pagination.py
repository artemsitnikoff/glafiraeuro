"""Пробное исследование пагинации `persons` в Talantix GraphQL.

Цель: понять, как реально работает `after` в `persons(first, after, filter)` —
есть ли pageInfo, endCursor, total, или нужна другая механика.

Запуск:
    .venv/bin/python scripts/probe_persons_pagination.py <vacancy_id> [stage_name]
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import talantix_token  # noqa: E402
from app.services.talantix_client import TalantixClient  # noqa: E402


PROBES = [
    # 1. Тип `Persons` — что в нём есть кроме items?
    ("Persons type fields", {
        "query": """
        query { __type(name: "Persons") {
          name kind fields { name type { name kind ofType { name kind } } }
        } }
        """,
    }),
    # 2. items + pageInfo (Relay-style)
    ("items + pageInfo", {
        "query": """
        query($vid: Int!, $first: Int!) {
          persons(first: $first, filter: {vacancyIds: [$vid]}) {
            items { ... on PersonItem { id } }
            pageInfo { hasNextPage endCursor }
          }
        }
        """,
    }),
    # 3. items + total / totalCount
    ("items + total", {
        "query": """
        query($vid: Int!, $first: Int!) {
          persons(first: $first, filter: {vacancyIds: [$vid]}) {
            items { ... on PersonItem { id } }
            total
          }
        }
        """,
    }),
    ("items + totalCount", {
        "query": """
        query($vid: Int!, $first: Int!) {
          persons(first: $first, filter: {vacancyIds: [$vid]}) {
            items { ... on PersonItem { id } }
            totalCount
          }
        }
        """,
    }),
    # 4. Cursor-based: after = id последнего как строка
    ("first=2, after='<last_id_str>'", {
        "query": """
        query($vid: Int!, $first: Int!, $after: String) {
          persons(first: $first, after: $after, filter: {vacancyIds: [$vid]}) {
            items { ... on PersonItem { id } }
          }
        }
        """,
        "needs_after": True,
    }),
]


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    vid = int(sys.argv[1])
    stage = sys.argv[2] if len(sys.argv) > 2 else None

    talantix_token.init_from_env()
    cl = TalantixClient()
    try:
        first_ids: list[int] = []
        for name, probe in PROBES:
            print(f"\n=== {name} ===")
            variables: dict = {"vid": vid, "first": 2}
            if stage and "filter" in probe["query"]:
                # Подменяем фильтр с этапом
                probe_q = probe["query"].replace(
                    "filter: {vacancyIds: [$vid]}",
                    'filter: {vacancyIds: [$vid], currentWfStatusNames: ["'
                    + stage.replace('"', '\\"') + '"]}',
                )
            else:
                probe_q = probe["query"]

            if probe.get("needs_after"):
                if not first_ids:
                    print("(нет первой страницы для after — пропуск)")
                    continue
                variables["after"] = str(first_ids[-1])

            try:
                data = await cl._gql(probe_q, variables)
                print(json.dumps(data, ensure_ascii=False, indent=2)[:1500])
                # Запомнить id из items если получились
                persons = data.get("persons") or {}
                items = persons.get("items") or []
                if items and not first_ids:
                    first_ids = [it["id"] for it in items if it and it.get("id")]
            except Exception as e:
                print(f"ERROR: {e}")
    finally:
        await cl.close()


if __name__ == "__main__":
    asyncio.run(main())
