"""
main.py — Entry point.

Responsibilities:
  1. Validate required environment variables.
  2. Initialise the SQLite database.
  3. Register all Telegram handlers.
  4. Start the APScheduler.
  5. Run the bot via long-polling.
"""
from __future__ import annotations

import logging
import sys

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.handlers import (
    agenda_command,
    decidir_command,
    fim_command,
    help_command,
    message_handler,
    planejar_command,
    prazo_command,
    projeto_command,
    resolver_command,
    revisao_command,
    start,
    status_command,
    tarefa_command,
)
from bot.scheduler import setup_scheduler
from db.models import initialize_db
from settings import ANTHROPIC_API_KEY, TELEGRAM_TOKEN, USER_CHAT_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _validate_config() -> None:
    errors: list[str] = []
    if not TELEGRAM_TOKEN:
        errors.append("TELEGRAM_TOKEN is not set")
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is not set")
    if not USER_CHAT_ID:
        errors.append("USER_CHAT_ID is not set or is 0")
    if errors:
        for err in errors:
            logger.critical("Configuration error: %s", err)
        sys.exit(1)


def main() -> None:
    _validate_config()

    # ── Database ──────────────────────────────────────────────────────────
    initialize_db()
    logger.info("Database ready")

    # ── Telegram application ──────────────────────────────────────────────
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Simple commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("projeto", projeto_command))
    app.add_handler(CommandHandler("prazo", prazo_command))
    app.add_handler(CommandHandler("tarefa", tarefa_command))
    app.add_handler(CommandHandler("agenda", agenda_command))
    app.add_handler(CommandHandler("resolver", resolver_command))

    # Conversational commands
    app.add_handler(CommandHandler("planejar", planejar_command))
    app.add_handler(CommandHandler("decidir", decidir_command))
    app.add_handler(CommandHandler("revisao", revisao_command))

    # Session close
    app.add_handler(CommandHandler("fim", fim_command))
    app.add_handler(CommandHandler("cancel", fim_command))

    # Catch-all text router (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # ── Scheduler ─────────────────────────────────────────────────────────
    scheduler = setup_scheduler(app.bot)
    scheduler.start()
    logger.info("Scheduler started with %d job(s)", len(scheduler.get_jobs()))

    # ── Start polling ─────────────────────────────────────────────────────
    logger.info("Orion is running — press Ctrl+C to stop")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
