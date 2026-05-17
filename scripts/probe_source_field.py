"""Исследование поля «источник кандидата» в Talantix.

Цель: найти, как читается «Отклик, hh.ru» у PersonItem, и какое поле
надо передавать в PersonEditInput, чтобы при `editPerson` источник не
сбрасывался в «Не указан».

Скрипт **read-only**: только запросы и validation-only мутации
(использует заведомо несуществующий id 99999999 — если поле
существует, validation пройдёт, но дальше будет PersonError/not found,
никакие данные не изменятся).

Запуск:
    docker compose exec bot python scripts/probe_source_field.py
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.talantix_client import TalantixClient  # noqa: E402


# Кандидаты на имя поля источника в PersonItem (read)
PERSON_FIELD_CANDIDATES = [
    "source",
    "sourceName",
    "sourceType",
    "origin",
    "originSource",
    "originName",
    "channel",
    "channelName",
    "import",
    "importSource",
    "importedFrom",
    "externalSource",
    "entryPoint",
    "responseSource",
    "applicationSource",
    "referralSource",
    "acquiredFrom",
    "acquiredVia",
    "via",
    "from",
    "createdFrom",
    "addedFrom",
    "vacancyResponse",
    "vacancyResponseSource",
]

# Кандидаты на «вложенные» поля источника (объект с подполями)
PERSON_OBJECT_CANDIDATES = [
    ("source", "name"),
    ("source", "title"),
    ("origin", "name"),
    ("origin", "title"),
    ("importSource", "name"),
    ("source", "id"),
]

# Кандидаты на имя поля в PersonEditInput
INPUT_FIELD_CANDIDATES = [
    "source",
    "sourceId",
    "sourceName",
    "origin",
    "originId",
    "originName",
    "channelId",
    "channelName",
    "importSource",
    "externalSource",
    "entryPoint",
    "responseSource",
    "applicationSource",
    "acquiredFrom",
    "from",
    "vacancyResponseSource",
]


async def _try_query(cl: TalantixClient, query: str, variables: dict | None = None) -> dict:
    """Возвращает {'ok': bool, 'data': dict?, 'errors': str?}"""
    try:
        data = await cl._gql(query, variables)
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "errors": str(e)[:600]}


async def find_test_person_id(cl: TalantixClient) -> int | None:
    """Найти id первого попавшегося кандидата на ИИ-этапе vacancy 1756375."""
    q = (
        'query { persons(first: 1, filter: {vacancyIds: [1756375], '
        'currentWfStatusNames: ["ИИ"]}) { items { ... on PersonItem { id } } } }'
    )
    r = await _try_query(cl, q)
    if not r["ok"]:
        return None
    items = (r["data"].get("persons") or {}).get("items") or []
    return items[0]["id"] if items else None


async def main():
    if len(sys.argv) > 1:
        person_id = int(sys.argv[1])
    else:
        person_id = None

    cl = TalantixClient()
    try:
        if person_id is None:
            person_id = await find_test_person_id(cl)
            if person_id is None:
                print("ERROR: не удалось найти тестового person_id")
                return
        print(f"Тестовый person_id = {person_id}\n")

        # ===== Часть 1: чтение PersonItem — скаляры =====
        print("=" * 60)
        print("Часть 1: ищем поле источника в PersonItem (скаляры)")
        print("=" * 60)
        found_scalar = []
        for fname in PERSON_FIELD_CANDIDATES:
            q = (
                'query($id: Int!) { person(id: $id) { ... on PersonItem { '
                + fname + ' } } }'
            )
            r = await _try_query(cl, q, {"id": person_id})
            if r["ok"]:
                node = r["data"].get("person") or {}
                value = node.get(fname)
                print(f"  ✅ {fname} = {value!r}")
                found_scalar.append((fname, value))
            else:
                # Тихо пропускаем FieldUndefined, шумим про остальное
                err = r["errors"]
                if "FieldUndefined" not in err and "Validation" not in err:
                    print(f"  ⚠️  {fname}: {err[:200]}")

        # ===== Часть 2: чтение PersonItem — объекты =====
        print()
        print("=" * 60)
        print("Часть 2: ищем поле источника в PersonItem (объекты)")
        print("=" * 60)
        found_obj = []
        for parent, child in PERSON_OBJECT_CANDIDATES:
            q = (
                'query($id: Int!) { person(id: $id) { ... on PersonItem { '
                + parent + ' { ' + child + ' } } } }'
            )
            r = await _try_query(cl, q, {"id": person_id})
            if r["ok"]:
                node = r["data"].get("person") or {}
                value = node.get(parent)
                print(f"  ✅ {parent}.{child} = {value!r}")
                found_obj.append((parent, child, value))
            else:
                err = r["errors"]
                if "FieldUndefined" not in err and "Validation" not in err:
                    print(f"  ⚠️  {parent}.{child}: {err[:200]}")

        # ===== Часть 3: PersonEditInput — какие поля принимает =====
        # Стратегия: пробуем editPerson с НЕсуществующим id 99999999.
        # Если поле есть в input — validation пройдёт, получим PersonError.
        # Если поля нет — FieldUndefined в input.
        print()
        print("=" * 60)
        print("Часть 3: ищем имя поля в PersonEditInput")
        print("=" * 60)
        print("(используем фейковый id 99999999 — данные не меняем)")
        found_input = []
        for fname in INPUT_FIELD_CANDIDATES:
            # Передаём значение как строку — большинство кандидатов скаляры
            q = (
                'mutation { editPerson(personEdit: { id: 99999999, '
                'firstName: "_probe_", lastName: "_probe_", '
                + fname + ': "test_value" }) { __typename } }'
            )
            r = await _try_query(cl, q)
            if r["ok"]:
                # Validation прошла, мутация дошла до исполнения
                tn = ((r["data"].get("editPerson") or {}).get("__typename"))
                print(f"  ✅ {fname}: validation OK, __typename={tn}")
                found_input.append(fname)
            else:
                err = r["errors"]
                if "FieldUndefined" in err:
                    pass  # тихо — поле точно отсутствует
                elif "WrongType" in err or "expected type" in err.lower():
                    # Поле есть, но мы передали не тот тип
                    print(f"  ⚠️  {fname}: поле ЕСТЬ, но не String → {err[:300]}")
                    found_input.append(fname)
                elif "Validation" in err:
                    print(f"  ❓ {fname}: {err[:300]}")
                else:
                    # Не validation — значит дошло до execution → поле есть
                    print(f"  ✅ {fname}: execution-уровень ошибка → поле есть. {err[:200]}")
                    found_input.append(fname)

        # ===== Итог =====
        print()
        print("=" * 60)
        print("ИТОГИ")
        print("=" * 60)
        print(f"PersonItem скаляр-поля с источником: {found_scalar or '— ничего не найдено'}")
        print(f"PersonItem объект-поля с источником: {found_obj or '— ничего не найдено'}")
        print(f"PersonEditInput кандидаты:           {found_input or '— ничего не найдено'}")

    finally:
        await cl.close()


if __name__ == "__main__":
    asyncio.run(main())
