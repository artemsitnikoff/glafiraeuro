"""Probe: как достать ВСЕ ACTIVE-вакансии (сервер капит vacancies на 200).

Перебираем механики: pageInfo+after, total/totalCount, серверный фильтр по
статусу, обратная сортировка. Интроспекция схемы заблокирована, поэтому
учимся по validation-ошибкам GraphQL.

Запуск: .venv/bin/python scripts/probe_vacancy_pagination.py
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import talantix_token  # noqa: E402
from app.services.talantix_client import TalantixClient  # noqa: E402


async def try_q(cl, label, query, variables=None):
    print(f"\n=== {label} ===")
    try:
        data = await cl._gql(query, variables or {})
        v = data.get("vacancies") or {}
        items = v.get("items") or []
        meta = {k: v[k] for k in v if k != "items"}
        print(f"  OK: items={len(items)} meta={meta}")
        return data
    except Exception as e:
        print(f"  ERR: {str(e)[:400]}")
        return None


async def main():
    talantix_token.init_from_env()
    cl = TalantixClient()
    try:
        # 1. pageInfo на Vacancies?
        await try_q(cl, "items + pageInfo", """
          query { vacancies(first: 200, sortBy: NAME, sortAsc: true) {
            items { ... on VacancyItem { id } }
            pageInfo { hasNextPage endCursor }
          } }
        """)

        # 2. total / totalCount?
        for fld in ("total", "totalCount", "count"):
            await try_q(cl, f"items + {fld}", """
              query { vacancies(first: 200) {
                items { ... on VacancyItem { id } }
                %s
              } }
            """ % fld)

        # 3. Серверный фильтр по статусу — перебор имён аргумента/поля
        status_filters = [
            ("filter:{statuses:[ACTIVE]}", 'filter: {statuses: [ACTIVE]}'),
            ("filter:{status:ACTIVE}", 'filter: {status: ACTIVE}'),
            ("filter:{statuses:[\"ACTIVE\"]}", 'filter: {statuses: ["ACTIVE"]}'),
            ("filter:{vacancyStatuses:[ACTIVE]}", 'filter: {vacancyStatuses: [ACTIVE]}'),
            ("filter:{state:ACTIVE}", 'filter: {state: ACTIVE}'),
            ("status:ACTIVE (arg)", None),  # отдельный аргумент
        ]
        for label, flt in status_filters:
            if flt is None:
                q = "query { vacancies(first: 200, status: ACTIVE) { items { ... on VacancyItem { id status } } } }"
            else:
                q = ("query { vacancies(first: 200, %s) { items { ... on VacancyItem { id status } } } }" % flt)
            d = await try_q(cl, label, q)
            if d:
                items = (d.get("vacancies") or {}).get("items") or []
                statuses = {}
                for it in items:
                    if it:
                        s = it.get("status") or "?"
                        statuses[s] = statuses.get(s, 0) + 1
                print(f"     по статусам: {statuses}")

        # 4. after с курсором-строкой (вдруг работает без pageInfo)
        # сначала возьмём id последнего из первой страницы
        first = await cl._gql(
            "query { vacancies(first: 200, sortBy: NAME, sortAsc: true) { items { ... on VacancyItem { id title } } } }"
        )
        items = (first.get("vacancies") or {}).get("items") or []
        if items:
            last = items[-1]
            print(f"\n  последний из первых 200: id={last.get('id')} '{last.get('title')}'")
            for after_val in (str(last.get("id")), str(len(items)), "200"):
                await try_q(cl, f"after='{after_val}'", """
                  query($a: String) { vacancies(first: 200, after: $a, sortBy: NAME, sortAsc: true) {
                    items { ... on VacancyItem { id title } }
                  } }
                """, {"a": after_val})

        # 5. Обратная сортировка — хвост алфавита (тут должна быть «Специалист…»)
        d = await try_q(cl, "sortAsc:false (хвост алфавита)", """
          query { vacancies(first: 200, sortBy: NAME, sortAsc: false) {
            items { ... on VacancyItem { id title status } }
          } }
        """)
        if d:
            items = (d.get("vacancies") or {}).get("items") or []
            active = [it for it in items if it and (it.get("status") or "").upper() == "ACTIVE"]
            print(f"     ACTIVE в обратной выборке: {len(active)}")
            for it in active:
                if "маркет" in (it.get("title") or "").lower() or "специалист" in (it.get("title") or "").lower():
                    print(f"       id={it.get('id')} status={it.get('status')} | {it.get('title')}")
            # есть ли вообще «Специалист по маркетингу»?
            for it in items:
                if it and (it.get("title") or "").strip().lower() == "специалист по маркетингу":
                    print(f"     >>> НАШЛАСЬ: id={it.get('id')} status={it.get('status')} | {it.get('title')}")
    finally:
        await cl.close()


if __name__ == "__main__":
    asyncio.run(main())
