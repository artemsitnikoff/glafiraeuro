"""FSM-роутер «Глафира»: вакансии → новые / переоценить → цикл оценки."""

import asyncio
import html as html_mod
import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.bot.routers.start import MENU_KB
from app.config import settings
from app.services.resume_scorer import score_person
from app.services.talantix_client import score_label
from app.services.talantix_models import Person, ScoringResult, Vacancy

logger = logging.getLogger("glafira")
router = Router()


def _parse_allowed_ids(csv: str) -> set[int]:
    if not csv.strip():
        return set()
    return {int(x.strip()) for x in csv.split(",") if x.strip().isdigit()}


RECRUITER_ALLOWED = _parse_allowed_ids(settings.recruiter_allowed)
SCORE_PREFIX_RE = re.compile(r"^\d+-")


def _is_scored(person: Person) -> bool:
    return bool(person.lastName and SCORE_PREFIX_RE.match(person.lastName))


def _format_count(n: int) -> str:
    """count_persons возвращает -1 если страниц больше → отрисуем как '50+'."""
    return "50+" if n < 0 else str(n)


class Recruiter(StatesGroup):
    choosing_job = State()
    confirming = State()
    scoring = State()


# ---------- entry: меню → список вакансий ----------


@router.callback_query(F.data == "recruit:menu")
async def show_vacancies(callback: CallbackQuery, state: FSMContext, talantix):
    if RECRUITER_ALLOWED and callback.from_user.id not in RECRUITER_ALLOWED:
        await callback.answer("🚧 Доступ ограничен", show_alert=True)
        return

    await callback.answer()
    wait = await callback.message.answer("👔 Загружаю вакансии из Talantix...")
    try:
        vacancies = await talantix.get_active_vacancies()
    except Exception as e:
        logger.error("Talantix error: %s", e, exc_info=True)
        await wait.edit_text(
            f"❌ Talantix недоступен: {html_mod.escape(str(e))}",
            reply_markup=MENU_KB,
        )
        return

    if not vacancies:
        await wait.edit_text("👔 Нет активных вакансий.", reply_markup=MENU_KB)
        return

    # Параллельно считаем кандидатов на этапе для каждой вакансии
    stage = settings.talantix_target_stage or None
    sem = asyncio.Semaphore(5)

    async def _count(v):
        async with sem:
            try:
                return v.id, await talantix.count_persons_for_vacancy(v.id, stage)
            except Exception as e:
                logger.warning("count_persons %s failed: %s", v.id, e)
                return v.id, 0

    counts_pairs = await asyncio.gather(*[_count(v) for v in vacancies])
    counts = dict(counts_pairs)

    # Сортируем: сначала те, где есть кандидаты на этапе
    vacancies.sort(key=lambda v: (-(counts.get(v.id) or 0), v.title))

    buttons: list[list[InlineKeyboardButton]] = []
    for v in vacancies[:30]:
        c = counts.get(v.id, 0)
        # Показываем только вакансии с кандидатами на этапе, если фильтр задан
        if stage and (c == 0):
            continue
        buttons.append([InlineKeyboardButton(
            text=f"{v.title} ({_format_count(c)})",
            callback_data=f"recruit:job:{v.id}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back:menu")])

    if len(buttons) == 1:  # одна только кнопка «◀️ Меню»
        await wait.edit_text(
            f"👔 Нет вакансий с кандидатами на этапе «{stage or '—'}».",
            reply_markup=MENU_KB,
        )
        return

    header = "👔 <b>Выбери вакансию:</b>"
    if stage:
        header += f"\n(этап: <b>{html_mod.escape(stage)}</b>, в скобках — кандидаты на этапе)"

    await wait.edit_text(
        header,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(Recruiter.choosing_job)


# ---------- вакансия → подсчёт новых/обработанных ----------


@router.callback_query(F.data.startswith("recruit:job:"), Recruiter.choosing_job)
async def choose_job(callback: CallbackQuery, state: FSMContext, talantix):
    job_id = int(callback.data.split(":")[-1])
    await callback.answer()

    progress = await callback.message.answer("👔 Загружаю вакансию...")

    try:
        job = await talantix.get_vacancy(job_id)
    except Exception as e:
        logger.error("get_vacancy %s: %s", job_id, e, exc_info=True)
        await progress.edit_text(
            f"❌ Ошибка загрузки вакансии: {html_mod.escape(str(e))}",
            reply_markup=MENU_KB,
        )
        await state.clear()
        return

    job_name = html_mod.escape(job.title)
    info_lines = [f"👔 <b>{job_name}</b>"]
    if job.department:
        info_lines.append(f"🏢 {html_mod.escape(job.department)}")
    info_lines.append("")

    desc_plain = re.sub(r"<[^>]+>", " ", job.description or "")
    desc_plain = re.sub(r"\s+", " ", desc_plain).strip()
    if desc_plain:
        info_lines.append(
            f"📋 <b>Описание:</b>\n{html_mod.escape(desc_plain[:1500])}"
        )
        info_lines.append("")

    stage = settings.talantix_target_stage or None
    if stage:
        info_lines.append(f"🎯 Этап: <b>{html_mod.escape(stage)}</b>")
    info_lines.append("⏳ Считаю кандидатов...")

    try:
        await progress.edit_text("\n".join(info_lines))
    except Exception:
        pass

    try:
        persons = await talantix.get_persons_for_vacancy(job_id, stage_name=stage)
    except Exception as e:
        logger.error("get_persons %s: %s", job_id, e, exc_info=True)
        info_lines[-1] = f"❌ Ошибка загрузки кандидатов: {html_mod.escape(str(e))}"
        await progress.edit_text("\n".join(info_lines), reply_markup=MENU_KB)
        await state.clear()
        return

    new_persons = [p for p in persons if not _is_scored(p)]
    scored_persons = [p for p in persons if _is_scored(p)]

    total_all = len(persons)
    total_new = len(new_persons)
    total_scored = len(scored_persons)
    logger.info(
        "Vacancy %s: %d total, %d new, %d already scored",
        job_id, total_all, total_new, total_scored,
    )

    if total_all == 0:
        info_lines[-1] = "Нет кандидатов на этой вакансии (на выбранном этапе)."
        await progress.edit_text("\n".join(info_lines), reply_markup=MENU_KB)
        await state.clear()
        return

    info_lines.pop()  # убираем "⏳ Считаю кандидатов..."

    buttons: list[list[InlineKeyboardButton]] = []
    if total_new > 0:
        buttons.append([InlineKeyboardButton(
            text=f"✅ Оценить новых ({total_new})",
            callback_data=f"recruit:score:{job_id}",
        )])
    buttons.append([InlineKeyboardButton(
        text=f"🔄 Переоценить всех ({total_all})",
        callback_data=f"recruit:rescore:{job_id}",
    )])
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back:menu")])

    await progress.edit_text(
        "\n".join(info_lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(Recruiter.confirming)
    await state.update_data(
        job_id=job_id,
        job=job.model_dump(),
        new_ids=[p.id for p in new_persons],
        all_ids=[p.id for p in persons],
    )


# ---------- цикл оценки ----------


def _format_result_message(
    job_name: str, idx: int, total: int, result: ScoringResult,
) -> str:
    label = score_label(result.score)
    name = html_mod.escape(result.person_name)
    jname = html_mod.escape(job_name)

    lines = [
        f"👔 <b>{jname}</b> [{idx}/{total}]",
        "",
        f"<b>{name}</b>",
        f"Балл: <b>{result.score}/100</b> ({label})",
        "",
        html_mod.escape(result.reasoning),
    ]

    if result.breakdown:
        lines.append("")
        lines.append("📊 <b>Разбивка по критериям:</b>")
        for b in result.breakdown:
            criterion = html_mod.escape(b.criterion)
            comment = html_mod.escape(b.comment) if b.comment else ""
            lines.append(f"  {criterion}: <b>{b.score}</b> — {comment}")

    if result.strengths:
        lines.append("")
        lines.append("✅ <b>Сильные стороны:</b>")
        for s in result.strengths:
            lines.append(f"  • {html_mod.escape(s)}")

    if result.weaknesses:
        lines.append("")
        lines.append("⚠️ <b>Слабые стороны:</b>")
        for w in result.weaknesses:
            lines.append(f"  • {html_mod.escape(w)}")

    if result.questions:
        lines.append("")
        lines.append("💬 <b>Вопросы для первого контакта:</b>")
        for q in result.questions:
            lines.append(f"  • {html_mod.escape(q)}")

    return "\n".join(lines)


@router.callback_query(F.data == "recruit:stop")
async def stop_scoring(callback: CallbackQuery, state: FSMContext):
    await state.update_data(stop=True)
    await callback.answer("Останавливаю после текущего кандидата...")


async def _run_scoring(
    callback: CallbackQuery,
    state: FSMContext,
    talantix,
    ai_client,
    job: Vacancy,
    person_ids: list[int],
):
    await state.set_state(Recruiter.scoring)

    total = len(person_ids)
    job_name = job.title
    scored_n = 0
    errors = 0

    stop_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹ Остановить", callback_data="recruit:stop")],
    ])

    for i, pid in enumerate(person_ids, 1):
        cur = await state.get_data()
        if cur.get("stop"):
            break

        thinking = await callback.message.answer(
            f"👔 <b>{html_mod.escape(job_name)}</b> [{i}/{total}]\n\n"
            f"⏳ Загружаю карточку...",
            reply_markup=stop_kb,
        )

        try:
            person = await talantix.get_person_full(pid)
            name = person.display_name
            try:
                await thinking.edit_text(
                    f"👔 <b>{html_mod.escape(job_name)}</b> [{i}/{total}]\n\n"
                    f"⏳ {html_mod.escape(name)}...",
                    reply_markup=stop_kb,
                )
            except Exception:
                pass

            result = await score_person(job, person, ai_client=ai_client)
            text = _format_result_message(job_name, i, total, result)
            if len(text) > 4096:
                text = text[:4090] + "\n…"
            try:
                await thinking.edit_text(text)
            except Exception:
                await thinking.delete()
                await callback.message.answer(text)

            scored_n += 1

            try:
                await talantix.push_scoring(result, person=person)
            except Exception as e:
                logger.error("push_scoring person %s: %s", pid, e)

        except Exception as e:
            logger.error("Scoring error for %s: %s", pid, e, exc_info=True)
            try:
                await thinking.edit_text(
                    f"👔 <b>{html_mod.escape(job_name)}</b> [{i}/{total}]\n\n"
                    f"❌ Ошибка: {html_mod.escape(str(e)[:200])}"
                )
            except Exception:
                pass
            errors += 1

    cur = await state.get_data()
    stopped = cur.get("stop", False)
    status = "остановлено" if stopped else "готово"
    summary = (
        f"👔 <b>{html_mod.escape(job_name)}</b> — {status}!\n\n"
        f"Оценено: {scored_n}/{total} | Ошибок: {errors}"
    )
    await callback.message.answer(summary, reply_markup=MENU_KB)
    await state.clear()


@router.callback_query(F.data.startswith("recruit:score:"), Recruiter.confirming)
async def score_new(callback: CallbackQuery, state: FSMContext, talantix, ai_client):
    await callback.answer()
    data = await state.get_data()
    job = Vacancy.model_validate(data["job"])
    await _run_scoring(callback, state, talantix, ai_client, job, data["new_ids"])


@router.callback_query(F.data.startswith("recruit:rescore:"), Recruiter.confirming)
async def rescore_all(callback: CallbackQuery, state: FSMContext, talantix, ai_client):
    await callback.answer()
    data = await state.get_data()
    job = Vacancy.model_validate(data["job"])
    await _run_scoring(callback, state, talantix, ai_client, job, data["all_ids"])
