import os

os.environ.setdefault("BOT_TOKEN", "test")

from app.utils import parse_json_response  # noqa: E402


def test_parse_clean_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_with_markdown_fence():
    text = "Here you go:\n```json\n{\"score\": 80, \"reasoning\": \"ok\"}\n```"
    assert parse_json_response(text) == {"score": 80, "reasoning": "ok"}


def test_parse_json_with_text_around():
    text = "Result: {\"score\": 50}\nDone."
    assert parse_json_response(text) == {"score": 50}
