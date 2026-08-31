"""
scheduler.py — APScheduler jobs alinhados à rotina do usuário.

Rotina diária:
  07:40  Levanta
  08:10  Academia
  09:00  Retorna, banho
  09:05  qui — projetos pessoais (dia inteiro)
  09:50  diário — checagem de prazos
  10:00  seg/ter/qua/sex — início do trabalho (Unifev)
  12:00  seg–sex — almoço
  13:45  seg/ter/qua/sex — retorno do almoço
  17:30  seg/ter/qua/sex — fim do expediente
  19:25  seg/ter/qua/sex — lembrete de aula
  19:30  seg/ter/qua/sex — aulas na Unifev
  23:00  fim das aulas
  23:30  diário — planejamento noturno
  domingo 18:00 — revisão semanal
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot

from bot.agent import AgentSession, send_message
from bot.context_builder import build_context, get_upcoming_deadlines
from db.models import Task
from bot.handlers import active_sessions
from db.models import Interaction
from prompts.system import (
    NIGHTLY_PLANNING_PROMPT,
    WEEKLY_REVIEW_PROMPT,
    build_system_prompt,
)
from settings import (
    PLANNING_TIME,
    TIMEZONE,
    USER_CHAT_ID,
    WEEKLY_REVIEW_DAY,
)

logger = logging.getLogger(__name__)

_DAY_MAP: dict[str, str] = {
    "monday": "mon",
    "segunda": "mon",
    "segunda-feira": "mon",
    "sunday": "sun",
    "domingo": "sun",
}

# Dias de trabalho na Unifev e de aula (não quinta, não fim de semana)
_WORKDAYS = "mon,tue,wed,fri"
_CLASS_DAYS = "mon,tue,wed,fri"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _send(bot: Bot, text: str, parse_mode: str = "Markdown") -> None:
    try:
        await bot.send_message(chat_id=USER_CHAT_ID, text=text, parse_mode=parse_mode)
    except Exception:
        logger.error("Failed to send message", exc_info=True)


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


async def nightly_planning(bot: Bot) -> None:
    """23:30 — Abre sessão de planejamento para o dia seguinte."""
    try:
        ctx = build_context()
        system = build_system_prompt(ctx) + "\n\n" + NIGHTLY_PLANNING_PROMPT
        session = AgentSession(session_type="nightly_planning", context=ctx)

        reply = await send_message(
            session,
            "Hora de planejar o dia de amanhã. Vamos lá!",
            system_prompt=system,
        )
        active_sessions[USER_CHAT_ID] = session
        await _send(bot, f"🌙 *Planejamento Noturno*\n\n{reply}")

        Interaction.create(
            type="nightly_planning",
            summary=f"Planejamento noturno iniciado em {date.today()}",
        )
        logger.info("Nightly planning sent")
    except Exception:
        logger.error("Nightly planning failed", exc_info=True)


async def deadline_check(bot: Bot) -> None:
    """09:50 — Alertas de projetos vencendo hoje, em 1, 3 ou 7 dias."""
    try:
        upcoming = get_upcoming_deadlines(days=7)
        thresholds = {0, 1, 3, 7}
        alerts: list[str] = []

        for p in upcoming:
            d = p["days_left"]
            if d not in thresholds:
                continue
            emoji = "🚨" if d == 0 else "🔴" if d == 1 else "🟡" if d == 3 else "🟢"
            label = "VENCE HOJE" if d == 0 else "amanhã" if d == 1 else f"em {d} dias"
            alerts.append(f"{emoji} *{p['name']}* — {p['deadline']} ({label})")

        if alerts:
            await _send(bot, "⏰ *Alertas de Prazo*\n\n" + "\n".join(alerts))
            logger.info("Sent %d deadline alert(s)", len(alerts))
    except Exception:
        logger.error("Deadline check failed", exc_info=True)


async def work_start_reminder(bot: Bot) -> None:
    """10:00 seg/ter/qua/sex — Início do trabalho com prazos do dia."""
    try:
        ctx = build_context()
        deadlines = ctx.get("upcoming_deadlines", [])

        lines = ["💼 *Bora trabalhar!* São 10h.\n"]
        if deadlines:
            lines.append("*Prazos esta semana:*")
            for p in deadlines[:3]:
                lines.append(f"• {p['name']} — {p['deadline']} ({p['days_left']}d)")
            lines.append("")
        lines.append("Use /planejar se precisar reorganizar o dia.")
        await _send(bot, "\n".join(lines))
    except Exception:
        logger.error("work_start_reminder failed", exc_info=True)


async def thursday_projects(bot: Bot) -> None:
    """09:05 qui — Dia inteiro livre para projetos pessoais."""
    try:
        ctx = build_context()
        projects = [p for p in ctx.get("active_projects", []) if p["status"] == "active"]

        lines = ["🛠️ *Quinta — dia de projetos pessoais!*\n"]
        if projects:
            lines.append("*Projetos ativos:*")
            for p in projects[:5]:
                dl = f"prazo {p['deadline']}" if p.get("deadline") else "sem prazo"
                lines.append(f"• [{p['id']}] {p['name']} ({dl})")
            lines.append("")
        lines.append("Bom proveito do dia! Use /planejar para definir o foco.")
        await _send(bot, "\n".join(lines))
    except Exception:
        logger.error("thursday_projects failed", exc_info=True)


async def lunch_reminder(bot: Bot) -> None:
    """12:00 seg–sex — Almoço."""
    await _send(bot, "🍽️ *Hora do almoço!* Volta às 13h45.")


async def afternoon_return(bot: Bot) -> None:
    """13:45 seg/ter/qua/sex — Retorno do almoço."""
    try:
        ctx = build_context()
        deadlines = ctx.get("upcoming_deadlines", [])
        lines = ["☕ *De volta ao trabalho.*\n"]
        if deadlines:
            lines.append("*Prazos próximos:*")
            for p in deadlines[:2]:
                lines.append(f"• {p['name']} — {p['days_left']}d")
        await _send(bot, "\n".join(lines))
    except Exception:
        logger.error("afternoon_return failed", exc_info=True)


async def end_of_work(bot: Bot) -> None:
    """17:30 seg/ter/qua/sex — Fim do expediente."""
    await _send(
        bot,
        "🏁 *Fim do expediente!*\n\n"
        "Vai pra casa, janta e descansa. Aulas às 19h30 — lembrete em breve.",
    )


async def class_reminder(bot: Bot) -> None:
    """19:25 seg/ter/qua/sex — Aula começa em 5 min."""
    await _send(bot, "📚 *Aula em 5 minutos!* Boa aula 🎓")


async def task_reminder_check(bot: Bot) -> None:
    """Cada minuto — Dispara lembretes de tarefas com horário definido."""
    try:
        now = datetime.now()
        today = now.date()
        current_time = now.strftime("%H:%M")

        due_tasks = list(
            Task.select().where(
                Task.due_date == today,
                Task.due_time == current_time,
                Task.reminder_sent == False,  # noqa: E712
                Task.status == "pending",
            )
        )

        for task in due_tasks:
            task.reminder_sent = True
            task.save()
            await _send(
                bot,
                f"⏰ *Lembrete:* {task.title}\n\n"
                f"Quer ajuda para resolver isso? Use `/resolver {task.id}`",
            )
            logger.info("Task reminder sent: id=%d title=%s", task.id, task.title)
    except Exception:
        logger.error("task_reminder_check failed", exc_info=True)


async def weekly_review(bot: Bot) -> None:
    """Domingo 18:00 — Revisão semanal conversacional."""
    try:
        ctx = build_context()
        system = build_system_prompt(ctx) + "\n\n" + WEEKLY_REVIEW_PROMPT
        session = AgentSession(session_type="weekly_review", context=ctx)

        reply = await send_message(
            session,
            "Vamos fazer a revisão da semana.",
            system_prompt=system,
        )
        active_sessions[USER_CHAT_ID] = session
        await _send(bot, f"📊 *Revisão Semanal*\n\n{reply}")

        Interaction.create(
            type="weekly_review",
            summary=f"Revisão semanal iniciada em {date.today()}",
        )
        logger.info("Weekly review sent")
    except Exception:
        logger.error("Weekly review failed", exc_info=True)


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Configura todos os jobs e retorna o scheduler (não iniciado)."""
    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    # -- Planejamento noturno (diário 23:30) --
    p_hour, p_minute = (int(x) for x in PLANNING_TIME.split(":"))
    scheduler.add_job(
        nightly_planning,
        CronTrigger(hour=p_hour, minute=p_minute, timezone=tz),
        args=[bot], id="nightly_planning", name="Nightly Planning", replace_existing=True,
    )

    # -- Checagem de prazos (diária 09:50) --
    scheduler.add_job(
        deadline_check,
        CronTrigger(hour=9, minute=50, timezone=tz),
        args=[bot], id="deadline_check", name="Deadline Check", replace_existing=True,
    )

    # -- Início do trabalho seg/ter/qua/sex 10:00 --
    scheduler.add_job(
        work_start_reminder,
        CronTrigger(day_of_week=_WORKDAYS, hour=10, minute=0, timezone=tz),
        args=[bot], id="work_start", name="Work Start", replace_existing=True,
    )

    # -- Quinta: projetos pessoais 09:05 --
    scheduler.add_job(
        thursday_projects,
        CronTrigger(day_of_week="thu", hour=9, minute=5, timezone=tz),
        args=[bot], id="thursday_projects", name="Thursday Projects", replace_existing=True,
    )

    # -- Almoço seg–sex 12:00 --
    scheduler.add_job(
        lunch_reminder,
        CronTrigger(day_of_week="mon,tue,wed,thu,fri", hour=12, minute=0, timezone=tz),
        args=[bot], id="lunch", name="Lunch Reminder", replace_existing=True,
    )

    # -- Retorno do almoço seg/ter/qua/sex 13:45 --
    scheduler.add_job(
        afternoon_return,
        CronTrigger(day_of_week=_WORKDAYS, hour=13, minute=45, timezone=tz),
        args=[bot], id="afternoon_return", name="Afternoon Return", replace_existing=True,
    )

    # -- Fim do expediente seg/ter/qua/sex 17:30 --
    scheduler.add_job(
        end_of_work,
        CronTrigger(day_of_week=_WORKDAYS, hour=17, minute=30, timezone=tz),
        args=[bot], id="end_of_work", name="End of Work", replace_existing=True,
    )

    # -- Lembrete de aula seg/ter/qua/sex 19:25 --
    scheduler.add_job(
        class_reminder,
        CronTrigger(day_of_week=_CLASS_DAYS, hour=19, minute=25, timezone=tz),
        args=[bot], id="class_reminder", name="Class Reminder", replace_existing=True,
    )

    # -- Revisão semanal domingo 18:00 --
    cron_day = _DAY_MAP.get(WEEKLY_REVIEW_DAY.lower(), "sun")
    scheduler.add_job(
        weekly_review,
        CronTrigger(day_of_week=cron_day, hour=18, minute=0, timezone=tz),
        args=[bot], id="weekly_review", name="Weekly Review", replace_existing=True,
    )

    # -- Lembretes de tarefas (a cada minuto) --
    scheduler.add_job(
        task_reminder_check,
        IntervalTrigger(minutes=1, timezone=tz),
        args=[bot], id="task_reminder", name="Task Reminder", replace_existing=True,
    )

    return scheduler
