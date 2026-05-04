"""Скоринг кандидата под вакансию через Claude CLI.

В Talantix всё содержимое резюме лежит плоской строкой в `StructuredResume.skills`
(включая опыт, навыки, образование). Скармливаем это AI как есть.
"""

import re
from typing import TYPE_CHECKING

from app.services.talantix_models import (
    Person,
    ScoreBreakdown,
    ScoringResult,
    Vacancy,
)
from app.utils import parse_json_response

if TYPE_CHECKING:
    from app.services.ai_client import AIClient

SCORING_PROMPT = """Ты — эксперт по подбору персонала. Оцени, насколько кандидат подходит под вакансию.

## Вакансия
Название: {job_name}
Отдел: {department}
Описание (HTML, не обращай внимания на теги):
{job_description}

## Кандидат
ФИО: {applicant_name}
Город: {applicant_city}
Заголовок резюме: {resume_title}

### Резюме (опыт, навыки, образование, достижения):
{resume_body}
{recruiter_instructions}
## Задача
Оцени кандидата по шкале от 0 до 100. Раздели оценку на критерии — выдели ключевые навыки и требования из вакансии и оцени кандидата по каждому отдельно. Сумма баллов по критериям = итоговый балл.

Примерные категории критериев (адаптируй под конкретную вакансию):
- Ключевые технические/профессиональные навыки (каждый важный навык отдельно)
- Релевантный опыт работы (годы, должности)
- Стабильность (частота смены работы)
- Образование
- Локация
- Зарплатные ожидания (если в резюме указаны)

Ответь СТРОГО в формате JSON (без markdown, без ```):
{{
  "score": <итог 0-100, сумма баллов по критериям>,
  "reasoning": "<краткое обоснование на русском, 1-2 предложения>",
  "breakdown": [
    {{"criterion": "<название критерия>", "score": <баллы>, "max_score": <макс возможный балл по этому критерию>, "comment": "<почему столько>"}}
  ],
  "strengths": ["<сильная сторона 1>"],
  "weaknesses": ["<слабая сторона 1>"],
  "questions": ["<вопрос для первого контакта 1>"]
}}

Важно: сумма всех `max_score` по критериям ДОЛЖНА быть равна 100. В `comment` НЕ упоминай «(макс N)» — это лишнее, максимум уже есть в поле `max_score`.

Для поля "questions": сгенерируй 3-5 конкретных вопросов для первого контакта с кандидатом. Вопросы должны уточнять пробелы или неясности в резюме, проверять ключевые навыки вакансии и помогать лучше понять реальный опыт кандидата."""


def extract_recruiter_instructions(description: str) -> tuple[str, str]:
    if not description:
        return description, ""
    match = re.search(r"(?:Важно для CLAUDE[:\s])(.*)", description, re.DOTALL | re.IGNORECASE)
    if match:
        instructions = match.group(1).strip()
        clean_desc = description[:match.start()].strip()
        return clean_desc, instructions
    return description, ""


def _build_prompt(job: Vacancy, person: Person) -> str:
    raw_desc = job.description or "Не указано"
    clean_desc, instructions = extract_recruiter_instructions(raw_desc)

    recruiter_block = ""
    if instructions:
        recruiter_block = f"\n## ОСОБЫЕ УКАЗАНИЯ РЕКРУТЕРА (обязательно учти!):\n{instructions}\n"

    applicant_city = (
        person.area.name if person.area and person.area.name else "Не указан"
    )

    return SCORING_PROMPT.format(
        job_name=job.title,
        department=job.department or "—",
        job_description=clean_desc[:6000],
        recruiter_instructions=recruiter_block,
        applicant_name=person.display_name,
        applicant_city=applicant_city,
        resume_title=person.resume_title or "Не указан",
        resume_body=(person.resume_text or "Не указано")[:12000],
    )


async def score_person(
    job: Vacancy, person: Person, *, ai_client: "AIClient",
) -> ScoringResult:
    prompt = _build_prompt(job, person)
    response_text = await ai_client.complete(prompt, timeout=300)
    result = parse_json_response(response_text)

    return ScoringResult(
        person_id=person.id,
        person_name=person.display_name,
        score=int(result["score"]),
        reasoning=result["reasoning"],
        strengths=result.get("strengths", []),
        weaknesses=result.get("weaknesses", []),
        breakdown=[ScoreBreakdown(**b) for b in result.get("breakdown", [])],
        questions=result.get("questions", []),
    )
