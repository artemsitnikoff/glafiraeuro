"""Диагностика рассинхрона вакансий/счётчиков бота vs Talantix UI.

Проверяем гипотезы по багу «вместо "Специалист по маркетингу" приходит
"crm-маркетолог", и счётчик на этапе ИИ не совпадает (бот 1, UI 10)»:

1. Сколько всего вакансий отдаёт vacancies(first:200) — упираемся ли в 200?
2. Есть ли пагинация вакансий (first=500/1000 — придёт больше 200?).
3. Где в выборке "Специалист по маркетингу" и "crm-маркетолог" (id, status,
   позиция в сортировке по NAME).
4. Для всех "маркет*" вакансий — count кандидатов на этапе ИИ + реальные
   имена этапов воронки у кандидатов.

Запуск:
    .venv/bin/python scripts/probe_vacancy_mismatch.py [stage_name]
"""

import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import talantix_token  # noqa: E402
from app.services.talantix_client import TalantixClient  # noqa: E402


VAC_QUERY = """
query Vacancies($first: Int!, $after: String) {
  vacancies(first: $first, after: $after, sortBy: NAME, sortAsc: true) {
    items { ... on VacancyItem { id title status } }
  }
}
""".strip()

# Кандидаты вакансии с именем текущего этапа воронки
PERSONS_STAGES_QUERY = """
query($first: Int!, $after: String, $filter: PersonFilterInput) {
  persons(first: $first, after: $after, filter: $filter) {
    items {
      ... on PersonItem {
        id firstName lastName
        currentWfStatus { ... on WfStatus { id name } }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()


async def fetch_vacancies(cl, first):
    data = await cl._gql(VAC_QUERY, {"first": first, "after": None})
    items = ((data.get("vacancies") or {}).get("items")) or []
    return [v for v in items if v]


async def persons_with_stages(cl, vacancy_id, stage=None, max_pages=200):
    """Все кандидаты вакансии (опц. фильтр по этапу) + распределение этапов.
    Если запрос с currentWfStatus упадёт (поля нет в схеме) — пробуем без него.
    """
    filter_ = {"vacancyIds": [vacancy_id]}
    if stage:
        filter_["currentWfStatusNames"] = [stage]
    rows = []
    cursor = None
    query = PERSONS_STAGES_QUERY
    for _ in range(max_pages):
        try:
            data = await cl._gql(query, {"first": 50, "after": cursor, "filter": filter_})
        except Exception as e:
            return None, f"query failed: {e}"
        obj = data.get("persons") or {}
        for it in (obj.get("items") or []):
            if not it:
                continue
            st = (it.get("currentWfStatus") or {}).get("name")
            rows.append((it.get("id"), f"{it.get('lastName') or ''} {it.get('firstName') or ''}".strip(), st))
        pi = obj.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
        if not cursor:
            break
    return rows, None


TYPE_FIELDS_Q = """
query($n: String!) {
  __type(name: $n) {
    name kind
    fields { name }
    inputFields { name type { name kind ofType { name kind } } }
  }
}
""".strip()


async def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else (settings.talantix_target_stage or "ИИ")
    talantix_token.init_from_env()
    cl = TalantixClient()
    try:
        # --- 0. Интроспекция: есть ли у вакансий пагинация / фильтр по статусу ---
        print("=== Схема: тип Vacancies (ищем pageInfo/total/endCursor) ===")
        for tname in ("Vacancies", "VacancyFilterInput"):
            try:
                d = await cl._gql(TYPE_FIELDS_Q, {"n": tname})
                t = d.get("__type") or {}
                flds = [f["name"] for f in (t.get("fields") or [])]
                inflds = [f["name"] for f in (t.get("inputFields") or [])]
                print(f"  {tname}: kind={t.get('kind')} "
                      f"fields={flds or '—'} inputFields={inflds or '—'}")
            except Exception as e:
                print(f"  {tname}: ERROR {e}")

        # --- 1. Сколько отдаёт first=200 ---
        v200 = await fetch_vacancies(cl, 200)
        print(f"=== vacancies(first=200): получено {len(v200)} ===")
        statuses = Counter((v.get("status") or "?") for v in v200)
        print(f"  по статусам: {dict(statuses)}")
        active200 = [v for v in v200 if (v.get('status') or '').upper() == 'ACTIVE']
        print(f"  ACTIVE: {len(active200)}")

        # --- 2. Пагинация: first=500 / 1000 даст больше? ---
        for f in (500, 1000):
            try:
                vf = await fetch_vacancies(cl, f)
                print(f"=== vacancies(first={f}): получено {len(vf)} ===")
            except Exception as e:
                print(f"=== vacancies(first={f}): ERROR {e}")

        # выбираем максимально полную выборку для поиска
        biggest = v200
        for f in (1000, 500):
            try:
                vf = await fetch_vacancies(cl, f)
                if len(vf) > len(biggest):
                    biggest = vf
            except Exception:
                pass

        # --- 3. Где маркетинговые вакансии ---
        print(f"\n=== Все вакансии с 'маркет' в названии (из выборки {len(biggest)}) ===")
        ordered = biggest  # уже в порядке сортировки NAME asc
        for idx, v in enumerate(ordered):
            title = (v.get("title") or "")
            if "маркет" in title.lower():
                print(f"  [pos {idx:>3}/{len(ordered)}] id={v.get('id')} "
                      f"status={v.get('status')} | {title}")

        # позиции конкретных вакансий по NAME-сортировке (видно, где обрезается 200)
        def find(title_sub):
            for idx, v in enumerate(ordered):
                if title_sub.lower() in (v.get("title") or "").lower():
                    return idx, v
            return None, None

        print("\n=== Позиции искомых вакансий в сортировке по NAME asc ===")
        for needle in ("crm-маркетолог", "Специалист по маркетингу"):
            idx, v = find(needle)
            if v:
                cut = "  <-- ЗА ПРЕДЕЛАМИ first=200!" if idx >= 200 else ""
                print(f"  '{needle}': pos {idx} id={v.get('id')} status={v.get('status')}{cut}")
            else:
                print(f"  '{needle}': НЕ НАЙДЕНА в выборке")

        # --- 4. Счётчики на этапе для всех маркетинговых ACTIVE ---
        print(f"\n=== Счётчики кандидатов (этап '{stage}') по маркетинговым ACTIVE-вакансиям ===")
        market_active = [v for v in ordered
                         if "маркет" in (v.get("title") or "").lower()
                         and (v.get("status") or "").upper() == "ACTIVE"]
        for v in market_active:
            vid = v.get("id")
            title = v.get("title")
            # текущий код бота: count_persons_for_vacancy
            try:
                bot_count = await cl.count_persons_for_vacancy(vid, stage)
            except Exception as e:
                bot_count = f"ERR {e}"
            # все кандидаты + распределение по этапам (без фильтра этапа)
            allrows, err = await persons_with_stages(cl, vid, stage=None)
            print(f"\n  id={vid} | {title}")
            print(f"    bot count_persons_for_vacancy(stage='{stage}') = {bot_count}")
            if err:
                print(f"    [stages] {err}")
            elif allrows is not None:
                dist = Counter(st for _, _, st in allrows)
                print(f"    всего кандидатов: {len(allrows)}; распределение по этапам:")
                for st, n in dist.most_common():
                    mark = "  <<< целевой?" if st and stage.lower() in st.lower() else ""
                    print(f"        {n:>4}  {st!r}{mark}")
    finally:
        await cl.close()


if __name__ == "__main__":
    asyncio.run(main())
