"""Проверка GraphQL-схемы Talantix.

Запуск:
    python scripts/introspect.py vacancy        # поля типа Vacancy
    python scripts/introspect.py person         # поля типа Person
    python scripts/introspect.py PersonFilterInput
    python scripts/introspect.py --query vacancies   # сигнатура query

Берёт токен из переменной TALANTIX_API_TOKEN (или из .env).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env()

TOKEN = os.environ.get("TALANTIX_API_TOKEN", "")
URL = os.environ.get("TALANTIX_BASE_URL", "https://api.talantix.ru/graphql")
UA = os.environ.get("TALANTIX_USER_AGENT", "GlafiraIntrospect/0.1 (artem@example.com)")


TYPE_QUERY = """
query Type($name: String!) {
  __type(name: $name) {
    name
    kind
    fields {
      name
      description
      type { name kind ofType { name kind ofType { name kind } } }
    }
    inputFields {
      name
      description
      type { name kind ofType { name kind ofType { name kind } } }
    }
  }
}
""".strip()


QUERY_FIELD_QUERY = """
query Q {
  __schema {
    queryType {
      fields {
        name
        description
        args {
          name
          type { name kind ofType { name kind ofType { name kind } } }
        }
        type { name kind ofType { name kind ofType { name kind } } }
      }
    }
  }
}
""".strip()


def _flat_type(t: dict) -> str:
    if not t:
        return "?"
    if t.get("name"):
        return t["name"]
    of = t.get("ofType")
    if of:
        suf = "!" if t.get("kind") == "NON_NULL" else "[]" if t.get("kind") == "LIST" else ""
        return _flat_type(of) + suf
    return t.get("kind", "?")


async def main():
    if not TOKEN:
        print("ОШИБКА: TALANTIX_API_TOKEN не задан в .env", file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": UA,
    }

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        if args[0] == "--query":
            resp = await client.post(URL, json={"query": QUERY_FIELD_QUERY})
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                print("GraphQL errors:", data["errors"])
                return
            fields = data["data"]["__schema"]["queryType"]["fields"]
            target = args[1] if len(args) > 1 else None
            for f in fields:
                if target and f["name"] != target:
                    continue
                args_str = ", ".join(
                    f"{a['name']}: {_flat_type(a['type'])}" for a in f["args"]
                )
                print(f"{f['name']}({args_str}): {_flat_type(f['type'])}")
                if f.get("description"):
                    print(f"  // {f['description']}")
            return

        # Тип по имени
        type_name = args[0]
        resp = await client.post(URL, json={"query": TYPE_QUERY, "variables": {"name": type_name}})
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            print("GraphQL errors:", data["errors"])
            return
        t = data["data"].get("__type")
        if not t:
            print(f"Тип '{type_name}' не найден")
            return
        print(f"=== {t['name']} ({t['kind']}) ===")
        for f in (t.get("fields") or []) + (t.get("inputFields") or []):
            print(f"  {f['name']}: {_flat_type(f['type'])}")
            if f.get("description"):
                print(f"    // {f['description']}")


if __name__ == "__main__":
    asyncio.run(main())
