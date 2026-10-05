import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.prompts import NLU_PROMPT, SKIP_CONFIRMATION
from app.schemas.patient_report import PatientResponseModel
from app.tools.backend_client import backend_client
from app.tools.rag_retriever import retriever

QUICK_REPLY_SETUP_TIME = "Перейти к настройке времени"

_NEGATIVE = ("не принял", "не принимал", "не выпил", "не пил", "не пью", "пропустил", "забыл", "отменил")
_POSITIVE = ("принял", "выпил", "приняла", "выпила", "принимал")
_PENDING = ("пока не", "еще не", "ещё не", "позже", "потом", "сейчас приму")
_SIDE = ("тошнит", "тошно", "тошнота", "кружится", "головокруж", "побоч", "плохо", "слабост", "сыпь", "боль")
_ADVICE = ("можно ли", "что делать", "питани", "как правильно", "что лучше", "можно")


def _valid_bp(systolic: Optional[int], diastolic: Optional[int]) -> bool:
    return (
        systolic is not None
        and diastolic is not None
        and 40 <= systolic <= 300
        and 20 <= diastolic <= 200
        and systolic > diastolic
    )


def sanitize_report(report: PatientResponseModel) -> PatientResponseModel:
    """Приводит разбор реплики (в т.ч. от LLM) к тому, что примет backend (иначе он ответит 422)."""
    if not _valid_bp(report.systolic, report.diastolic):
        report.systolic = report.diastolic = None
    if report.pulse is not None and not 20 <= report.pulse <= 250:
        report.pulse = None
    if report.medication_taken is not False:
        report.skip_reason = None  # причина пропуска имеет смысл только при пропуске
    return report


def _fallback_parse(message: str) -> PatientResponseModel:
    """Разбор реплики по правилам (когда LLM недоступен): давление, пульс, прием таблетки, жалобы."""
    low = message.lower().replace("ё", "е")

    systolic = diastolic = pulse = None
    m = re.search(r"(\d{2,3})\s*(?:/|\\|на|из)\s*(\d{2,3})", low)
    if not m:
        m = re.search(r"(?:давлени\w*|\bад\b)\D{0,12}?(\d{2,3})[\s,;и]{1,4}(\d{2,3})", low)
    if m:
        systolic, diastolic = int(m.group(1)), int(m.group(2))
    pm = re.search(r"(?:пульс|pulse|чсс)\D{0,10}(\d{2,3})", low) or re.search(r"(\d{2,3})\s*уд", low)
    if pm:
        pulse = int(pm.group(1))

    pending = any(x in low for x in _PENDING)
    negative = any(x in low for x in _NEGATIVE) and not pending
    positive = any(x in low for x in _POSITIVE) and not any(x in low for x in _NEGATIVE)
    taken: Optional[bool] = False if negative else True if positive else None
    side = any(x in low for x in _SIDE)

    reason = None
    if taken is False:
        if side:
            reason = "side_effects"
        elif "забыл" in low:
            reason = "forgot"
        elif "не успел" in low or "поздно" in low:
            reason = "late"
        else:
            reason = "other"

    has_data = systolic is not None or pulse is not None or taken is not None
    if side:
        intent = "complain_side_effects"
    elif has_data:
        intent = "report_data"
    elif any(x in low for x in _ADVICE):
        intent = "ask_advice"
    else:
        intent = "general_chat"

    return sanitize_report(
        PatientResponseModel(
            systolic=systolic,
            diastolic=diastolic,
            pulse=pulse,
            medication_taken=taken,
            skip_reason=reason,
            raw_complaint=message if side else None,
            intent=intent,
        )
    )


async def _llm_parse(message: str) -> PatientResponseModel:
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0,
        timeout=settings.request_timeout,
    )
    structured = llm.with_structured_output(PatientResponseModel)
    parsed = await structured.ainvoke([{"role": "system", "content": NLU_PROMPT}, {"role": "user", "content": message}])
    return sanitize_report(parsed)


def _last_user_text(state: dict[str, Any]) -> str:
    messages = state.get("messages") or []
    if not messages:
        return ""
    last = messages[-1]
    return str(getattr(last, "content", None) or (last.get("content") if isinstance(last, dict) else "") or "")


def has_report_data(parsed: Optional[dict[str, Any]]) -> bool:
    parsed = parsed or {}
    return any(parsed.get(k) is not None for k in ("systolic", "pulse", "medication_taken"))


def _times_word(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "несколько раз"
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} раз"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} раза"
    return f"{n} раз"


def _format_slot_time(value: str) -> str:
    """ISO-время слота из бэкенда (UTC, суффикс Z) -> 'дд.мм чч:мм' в часовом поясе пациента."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(settings.timezone)).strftime("%d.%m %H:%M")
    except Exception:
        return value


async def greeting_node(state: dict[str, Any]):
    plan = state.get("treatment_plan")
    if plan is None:
        try:
            plan = await backend_client.get_treatment_plan(state["patient_id"], state["jwt_token"])
        except Exception as exc:
            return {
                "response_text": "Не удалось получить назначение из системы. Пожалуйста, попробуйте ещё раз.",
                "quick_replies": [],
                "error": str(exc),
            }
    doctor = plan.get("doctor_name") or "врач"
    medication = plan.get("medication") or plan.get("prescribed_medication") or "назначенный препарат"
    frequency = _times_word(plan.get("frequency_per_day", plan.get("frequency", 2)))
    target = plan.get("target_bp") or f"{plan.get('target_systolic', 130)}/{plan.get('target_diastolic', 80)}"
    text = (
        f"Здравствуйте! Врач {doctor} назначил вам {medication} с приемом {frequency} в день "
        f"(целевое давление {target}). Я буду помогать вам вести дневник наблюдений: "
        "пришлите давление, пульс или расскажите о самочувствии. "
        "Пожалуйста, укажите в настройках удобное время для утреннего и вечернего напоминания."
    )
    return {"treatment_plan": plan, "response_text": text, "quick_replies": [QUICK_REPLY_SETUP_TIME]}


async def nlu_node(state: dict[str, Any]):
    message = _last_user_text(state)
    try:
        parsed = await _llm_parse(message) if settings.llm_api_key else _fallback_parse(message)
    except Exception:
        parsed = _fallback_parse(message)
    return {"parsed_report": parsed.model_dump()}


async def rag_advice_node(state: dict[str, Any]):
    docs = retriever.search(_last_user_text(state))
    if docs:
        answer = (
            "По утвержденным материалам CardioFlow:\n\n" + "\n\n".join(docs[:2]) +
            "\n\nЭто общая информация, индивидуальные рекомендации даёт ваш врач."
        )
    else:
        answer = (
            "Я могу помочь зафиксировать ваши показатели и передать вопрос врачу. "
            "Индивидуальные медицинские рекомендации без подтвержденных материалов я не даю."
        )
    return {"response_text": answer, "quick_replies": []}


async def chat_node(state: dict[str, Any]):
    """Реплики без данных для отчета: приветствия, 'я в порядке', 'пока не принял' и т.п."""
    low = _last_user_text(state).lower()
    if "настрой" in low and ("время" in low or "напомин" in low):
        text = "Время утреннего и вечернего приема можно задать на странице «Лечение» в разделе «Расписание приема»."
    elif any(x in low for x in _PENDING):
        text = "Хорошо. Не забудьте принять препарат по назначению врача, а потом напишите мне, как самочувствие."
    else:
        text = (
            "Я здесь, чтобы помочь вести дневник. Напишите давление (например, 130/85), пульс, "
            "принимали ли вы лекарство и как себя чувствуете."
        )
    return {"response_text": text, "quick_replies": []}


async def backend_report_node(state: dict[str, Any]):
    parsed = state.get("parsed_report") or {}
    report = {
        key: parsed.get(key)
        for key in ("systolic", "diastolic", "pulse", "medication_taken", "skip_reason", "raw_complaint")
    }
    report["patient_id"] = state["patient_id"]
    try:
        result = await backend_client.submit_patient_report(report, state["jwt_token"])
    except Exception as exc:
        return {
            "response_text": "Не удалось сохранить данные в CardioFlow. Пожалуйста, повторите отправку.",
            "quick_replies": [],
            "error": str(exc),
        }
    return {
        "risk_level": result.get("risk_level"),
        "action_required": result.get("action_required"),
        "backend_result": result,
    }


async def clarify_symptoms_node(state: dict[str, Any]):
    parsed = state.get("parsed_report") or {}
    action = state.get("action_required")
    risk = state.get("risk_level")
    parts = []
    if parsed.get("systolic") is not None:
        parts.append(f"Я записал давление {parsed['systolic']}/{parsed['diastolic']}.")
    if parsed.get("medication_taken") is False and parsed.get("skip_reason") == "side_effects":
        parts.append(SKIP_CONFIRMATION)

    if action == "book_appointment":
        parts.append("Пожалуйста, присядьте и спокойно отдохните. Как давно появились симптомы и сохраняются ли они сейчас?")
    elif risk == "warning" or action == "repeat_measurement":
        parts.append(
            "Показатель выше целевого. Посидите спокойно 5 минут и повторите измерение; "
            "если станет хуже, напишите мне."
        )
    elif parsed.get("raw_complaint"):
        parts.append("Спасибо, я зафиксировал ваше самочувствие. Как давно появились эти симптомы и сохраняются ли они сейчас?")
    else:
        parts.append(
            "Пожалуйста, присядьте и спокойно отдохните. Уточните, как вы себя сейчас чувствуете: "
            "есть ли головная боль, тошнота или головокружение?"
        )
    return {"response_text": " ".join(parts), "quick_replies": []}


async def slots_proposal_node(state: dict[str, Any]):
    base = state.get("response_text") or ""
    try:
        slots = await backend_client.search_available_slots(state["jwt_token"], limit=3)
    except Exception as exc:
        text = (base + "\n\n" if base else "") + "Сейчас не удалось получить свободные окна врача. Пожалуйста, попробуйте позже."
        return {"available_slots": [], "response_text": text, "quick_replies": [], "error": str(exc)}
    if not slots:
        extra = "Сейчас свободных окон к врачу не найдено. Я сохранил данные, и вы можете повторить поиск позже."
    else:
        formatted = "\n".join(f"• {s.get('doctor_name', 'Врач')} — {_format_slot_time(s.get('datetime', ''))}" for s in slots)
        extra = "Ближайшие окна для записи (также откроется окно записи):\n" + formatted
    return {"available_slots": slots, "response_text": (base + "\n\n" if base else "") + extra, "quick_replies": []}


async def confirmation_node(state: dict[str, Any]):
    parsed = state.get("parsed_report") or {}
    saved = []
    if parsed.get("systolic") is not None:
        saved.append(f"давление {parsed['systolic']}/{parsed['diastolic']}")
    if parsed.get("pulse") is not None:
        saved.append(f"пульс {parsed['pulse']}")
    if parsed.get("medication_taken") is True:
        saved.append("прием лекарства отмечен")
    elif parsed.get("medication_taken") is False:
        saved.append("пропуск приема отмечен")
    text = "Спасибо, зафиксировал: " + ", ".join(saved) + "." if saved else "Спасибо, зафиксировал ваши данные."
    return {"response_text": text, "quick_replies": []}
