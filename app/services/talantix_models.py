"""Pydantic-модели ответов Talantix GraphQL (реальная схема, по введению)."""

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class Area(_Base):
    id: int | None = None
    name: str | None = None


class StructuredResume(_Base):
    """В Talantix `StructuredResume.skills` — это плоский текст резюме целиком
    (опыт, навыки, обучение, достижения). Поле `title` — заголовок резюме.
    """
    id: int | None = None
    title: str | None = None
    skills: str | None = None  # ВЕСЬ текст резюме плоской строкой


class Vacancy(_Base):
    """Возвращается из vacancies/items и vacancy(id). Обе ветки содержат
    одни и те же поля — Vacancy(interface) → VacancyItem.
    """
    id: int
    title: str
    status: str | None = None  # ACTIVE / ARCHIVE / ...
    department: str | None = None
    description: str | None = None
    url: str | None = None
    createdAt: int | None = None

    @property
    def name(self) -> str:
        """Алиас, чтобы код в роутере мог использовать .name (как у Potok)."""
        return self.title

    @property
    def is_active(self) -> bool:
        return (self.status or "").upper() == "ACTIVE"


class PersonTag(_Base):
    id: int | None = None
    name: str | None = None


class ContactItem(_Base):
    type: str | None = None  # cell, email, work, home, telegram, ...
    value: str | None = None


class Person(_Base):
    """PersonItem из persons/items и person(id) (с обработкой PersonError)."""
    id: int
    firstName: str | None = None
    lastName: str | None = None
    middleName: str | None = None
    gender: str | None = None
    birthDay: int | None = None  # timestamp ms
    updatedAt: int | None = None
    area: Area | None = None
    # Список тегов кандидата (имя тега начинается с "AI: " если оценен AI)
    tag_names: list[str] = []
    # Дозагружается через get_person_full() — нужно для безопасного editPerson
    contacts_list: list[ContactItem] = []
    citizenship_ids: list[str] = []
    # Заполняется только в "полной" карточке через person(id)
    resume_text: str | None = None
    resume_title: str | None = None

    @property
    def display_name(self) -> str:
        parts = [self.lastName, self.firstName, self.middleName]
        joined = " ".join(p for p in parts if p)
        return joined or f"ID:{self.id}"


class ScoreBreakdown(BaseModel):
    criterion: str
    score: int
    max_score: int = 0
    comment: str = ""


class ScoringResult(BaseModel):
    person_id: int
    person_name: str
    score: int
    reasoning: str
    strengths: list[str] = []
    weaknesses: list[str] = []
    breakdown: list[ScoreBreakdown] = []
    questions: list[str] = []
