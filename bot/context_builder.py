"""
context_builder.py — Reads the database and assembles the dynamic context dict
that is injected into every system prompt.

All functions return safe, serialisable dicts so callers don't need to touch
Peewee models directly.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from db.models import Decision, Interaction, Project, Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Project helpers
# ---------------------------------------------------------------------------


def get_active_projects() -> list[dict]:
    """Return all active projects ordered by deadline (NULLs last)."""
    try:
        from peewee import SQL

        rows = (
            Project.select()
            .where(Project.status == "active")
            # SQL("deadline IS NULL") evaluates to 1 for NULL → sorts last
            .order_by(SQL("deadline IS NULL"), Project.deadline.asc())
        )
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "deadline": str(p.deadline) if p.deadline else None,
                "status": p.status,
            }
            for p in rows
        ]
    except Exception:
        logger.error("Error fetching active projects", exc_info=True)
        return []


def get_upcoming_deadlines(days: int = 7) -> list[dict]:
    """Return active projects whose deadline falls within *days* from today."""
    try:
        today = date.today()
        horizon = today + timedelta(days=days)
        rows = (
            Project.select()
            .where(
                Project.status == "active",
                Project.deadline.is_null(False),
                Project.deadline >= today,
                Project.deadline <= horizon,
            )
            .order_by(Project.deadline.asc())
        )
        return [
            {
                "id": p.id,
                "name": p.name,
                "deadline": str(p.deadline),
                "days_left": (p.deadline - today).days,
            }
            for p in rows
        ]
    except Exception:
        logger.error("Error fetching upcoming deadlines", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Decision helpers
# ---------------------------------------------------------------------------


def get_recent_decisions(limit: int = 3) -> list[dict]:
    """Return the most recent recorded decisions."""
    try:
        rows = Decision.select().order_by(Decision.created_at.desc()).limit(limit)
        return [
            {
                "date": d.created_at.strftime("%d/%m"),
                "context": d.context,
                "conclusion": d.conclusion,
                "rationale": d.rationale,
            }
            for d in rows
        ]
    except Exception:
        logger.error("Error fetching recent decisions", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Interaction helpers
# ---------------------------------------------------------------------------


def get_last_interactions(limit: int = 5) -> list[dict]:
    """Return the most recent interaction summaries."""
    try:
        rows = (
            Interaction.select()
            .order_by(Interaction.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "date": i.created_at.strftime("%d/%m"),
                "type": i.type,
                "summary": i.summary,
            }
            for i in rows
        ]
    except Exception:
        logger.error("Error fetching interactions", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Main context builder
# ---------------------------------------------------------------------------


def build_context() -> dict:
    """Aggregate all context pieces into a single dict for prompt injection."""
    return {
        "active_projects": get_active_projects(),
        "upcoming_deadlines": get_upcoming_deadlines(),
        "recent_decisions": get_recent_decisions(),
        "last_interactions": get_last_interactions(),
    }


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        return Settings.get(Settings.key == key).value
    except Settings.DoesNotExist:
        return default
    except Exception:
        logger.error("Error reading setting '%s'", key, exc_info=True)
        return default


def set_setting(key: str, value: str) -> None:
    try:
        Settings.insert(key=key, value=value).on_conflict_replace().execute()
    except Exception:
        logger.error("Error writing setting '%s'", key, exc_info=True)
