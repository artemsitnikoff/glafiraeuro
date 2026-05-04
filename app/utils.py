import json
import re


def parse_json_response(text: str) -> dict:
    """Извлечь JSON-объект из ответа AI. Терпим к ```json fences и тексту вокруг."""
    text = text.strip()

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    return json.loads(text)
