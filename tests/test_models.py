import os

os.environ.setdefault("BOT_TOKEN", "test")

from app.services.talantix_models import (  # noqa: E402
    Person,
    ScoringResult,
    Vacancy,
)


def test_vacancy_basic():
    v = Vacancy.model_validate({
        "id": 1, "title": "Dev", "status": "ACTIVE", "department": "IT",
    })
    assert v.id == 1
    assert v.is_active
    assert v.name == "Dev"


def test_vacancy_archive_not_active():
    v = Vacancy(id=2, title="Old", status="ARCHIVE")
    assert not v.is_active


def test_vacancy_extra_fields_allowed():
    v = Vacancy.model_validate({
        "id": 1, "title": "Dev",
        "someUnknownField": "ok",
        "createdAt": 1700000000,
    })
    assert v.id == 1


def test_person_display_name_full():
    p = Person(id=1, lastName="Иванов", firstName="Иван", middleName="Иваныч")
    assert p.display_name == "Иванов Иван Иваныч"


def test_person_display_name_fallback_to_id():
    p = Person(id=42)
    assert p.display_name == "ID:42"


def test_person_resume_text_optional():
    p = Person(id=1, firstName="A", lastName="B", resume_text="long text", resume_title="Dev")
    assert p.resume_text == "long text"
    assert p.resume_title == "Dev"


def test_scoring_result_basic():
    r = ScoringResult(
        person_id=1, person_name="Иванов",
        score=85, reasoning="ok",
    )
    assert r.score == 85
    assert r.breakdown == []
