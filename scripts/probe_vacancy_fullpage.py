"""Проверка фикса: сквозная курсорная пагинация vacancies по endCursor.

Собираем ВСЕ вакансии (count=1537), считаем ACTIVE, проверяем что
«Специалист по маркетингу» (id=1825270) теперь в выборке и её счётчик
на этапе ИИ совпадает с тем, что видит пользователь (~10).

Запуск: .venv/bin/python scripts/probe_vacancy_fullpage.py
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import talantix_token  # noqa: E402
from app.services.talantix_client import TalantixClient  # noqa: E402

PAGE_Q = """
query($first: Int!, $after: String) {
  vacancies(first: $first, after: $after, sortBy: NAME, sortAsc: true) {
    count
    items { ... on VacancyItem { id title status } }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()


async def main():
    talantix_token.init_from_env()
    cl = TalantixClient()
    try:
        all_items = []
        cursor = None
        pages = 0
        declared = None
        while pages < 50:
            data = await cl._gql(PAGE_Q, {"first": 200, "after": cursor})
            v = data.get("vacancies") or {}
            if declared is None:
                declared = v.get("count")
            items = [it for it in (v.get("items") or []) if it]
            all_items.extend(items)
            pages += 1
            pi = v.get("pageInfo") or {}
            print(f"  page {pages}: +{len(items)} (итого {len(all_items)}), "
                  f"hasNextPage={pi.get('hasNextPage')}")
            if not pi.get("hasNextPage"):
                break
            cursor = pi.get("endCursor")
            if not cursor:
                break

        print(f"\n=== Собрано {len(all_items)} вакансий, declared count={declared} ===")
        active = [it for it in all_items if (it.get("status") or "").upper() == "ACTIVE"]
        print(f"ACTIVE: {len(active)}")

        # дубликаты id?
        ids = [it["id"] for it in all_items]
        print(f"уникальных id: {len(set(ids))} из {len(ids)}")

        print("\n=== Все ACTIVE-вакансии (отсортированы по имени) ===")
        for it in sorted(active, key=lambda x: (x.get("title") or "")):
            print(f"  id={it['id']:>8} | {it.get('title')}")

        # Целевая вакансия
        target = [it for it in active if it["id"] == 1825270]
        print(f"\n=== 'Специалист по маркетингу' (1825270) в ACTIVE-выборке: "
              f"{'ДА' if target else 'НЕТ'} ===")

        # Счётчики ИИ по маркетинговым ACTIVE
        print("\n=== Счётчик этапа ИИ по маркетинговым ACTIVE-вакансиям ===")
        for it in active:
            t = (it.get("title") or "")
            if "маркет" in t.lower():
                cnt = await cl.count_persons_for_vacancy(it["id"], "ИИ")
                print(f"  id={it['id']:>8} ИИ={cnt:>4} | {t}")
    finally:
        await cl.close()


if __name__ == "__main__":
    asyncio.run(main())
