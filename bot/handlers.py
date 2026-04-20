"""
handlers.py — Telegram command and message handlers.

Session management strategy
----------------------------
Instead of ConversationHandler (which conflicts with scheduler-injected sessions),
we use a module-level ``active_sessions`` dict keyed by user_id.  Any command
that starts a multi-turn flow stores an AgentSession there.  The scheduler can
also insert a session when it fires the morning ritual.  Every plain text
message is routed to the active session, if one exists.

Commands:
  /start            — help & command list
  /status           — upcoming deadlines
  /projeto add|list — project management
  /prazo <id> <date>— update deadline
  /planejar         — daily planning session
  /decidir [ctx]    — decision support (Sonnet)
  /revisao          — weekly review session
  /fim | /cancel    — close active session
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from telegram import Update
from telegram.ext import ContextTypes

from bot.agent import AgentSession, send_message, summarize_conversation
from bot.context_builder import build_context, get_upcoming_deadlines
from db.models import DailyPlan, Decision, Interaction, Project
from prompts.system import (
    DECISION_PROMPT,
    NIGHTLY_PLANNING_PROMPT,
    PLANNING_PROMPT,
    WEEKLY_REVIEW_PROMPT,
    build_system_prompt,
)
from settings import USER_CHAT_ID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state (lives for the lifetime of the process)
# ---------------------------------------------------------------------------

# user_id → AgentSession
active_sessions: dict[int, AgentSession] = {}

# Extra system-prompt fragment appended per session type
_SESSION_EXTRA: dict[str, str] = {
    "nightly_planning": NIGHTLY_PLANNING_PROMPT,
    "planning": PLANNING_PROMPT,
    "decision": DECISION_PROMPT,
    "weekly_review": WEEKLY_REVIEW_PROMPT,
}


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def _authorized(user_id: int) -> bool:
    return user_id == USER_CHAT_ID


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "*Orion — Agente de Produtividade* 🌟\n\n"
        "*Conversas guiadas*\n"
        "• /planejar — Planejar o dia\n"
        "• /decidir \\[contexto\\] — Apoio a decisões complexas\n"
        "• /revisao — Revisão semanal\n"
        "• /fim — Encerrar conversa ativa\n\n"
        "*Projetos*\n"
        "• /projeto add \\<nome\\> \\[YYYY\\-MM\\-DD\\] — Novo projeto\n"
        "• /projeto list — Listar projetos ativos\n"
        "• /prazo \\<id\\> \\<YYYY\\-MM\\-DD\\> — Atualizar prazo\n\n"
        "*Visão geral*\n"
        "• /status — Prazos próximos\n\n"
        "• /help — Ajuda detalhada e fluxo do bot",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

_HELP_TEXT = """
📖 *Guia do Orion*

━━━━━━━━━━━━━━━━━
🗓 *PLANEJAMENTO*
━━━━━━━━━━━━━━━━━
*/planejar*
Inicia uma conversa guiada para montar o plano do dia.
O Orion considera seus projetos ativos e prazos próximos.
Responda livremente até ter seu plano. Use /fim para salvar.

*Automático às 23:30 (diário)*
O bot pede para você planejar o dia seguinte antes de dormir.
Basta responder normalmente — a conversa fica aberta.

━━━━━━━━━━━━━━━━━
🧠 *DECISÕES*
━━━━━━━━━━━━━━━━━
*/decidir [contexto]*
Abre o modo de apoio a decisões (usa Claude Sonnet — mais potente).
Exemplos:
  • /decidir aceitar ou recusar essa proposta de projeto?
  • /decidir qual tecnologia usar no novo sistema?

O Orion faz perguntas estruturadas, mapeia opções e te ajuda a concluir.
A decisão final é salva no histórico. Use /fim para encerrar.

━━━━━━━━━━━━━━━━━
📁 *PROJETOS E PRAZOS*
━━━━━━━━━━━━━━━━━
*/projeto add <nome> [YYYY-MM-DD]*
Cadastra um projeto. O prazo é opcional.
  • /projeto add Site do cliente 2026-05-10
  • /projeto add Artigo TCC

*/projeto list*
Lista todos os projetos ativos com ID e prazo.

*/prazo <id> <YYYY-MM-DD>*
Atualiza o prazo de um projeto pelo ID.
  • /prazo 3 2026-06-01

*/status*
Mostra projetos com prazo nos próximos 14 dias.

━━━━━━━━━━━━━━━━━
📊 *REVISÃO SEMANAL*
━━━━━━━━━━━━━━━━━
*/revisao*
Inicia a revisão semanal manualmente.
Resume a semana, decisões tomadas e define foco da próxima semana.

*Automático todo domingo às 18:00*

━━━━━━━━━━━━━━━━━
⏰ *LEMBRETES AUTOMÁTICOS*
━━━━━━━━━━━━━━━━━
O bot envia notificações automáticas conforme sua rotina:
  • 09:05 qui — Foco em projetos pessoais
  • 09:50 diário — Alertas de prazo (hoje / 1d / 3d / 7d)
  • 10:00 seg–sex — Início do trabalho
  • 12:00 seg–sex — Almoço
  • 13:45 seg/ter/qua/sex — Retorno do almoço
  • 17:30 seg/ter/qua/sex — Fim do expediente
  • 19:25 seg/ter/qua/sex — Aula em 5 min
  • 23:30 diário — Planejamento noturno

━━━━━━━━━━━━━━━━━
💬 *CONVERSAS*
━━━━━━━━━━━━━━━━━
Após iniciar /planejar, /decidir ou /revisao, basta *digitar normalmente* — \
o Orion responde no contexto da conversa ativa.
*/fim* — encerra a conversa, gera resumo e salva no histórico.
""".strip()


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return
    await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return

    deadlines = get_upcoming_deadlines(days=14)
    if not deadlines:
        await update.message.reply_text("Nenhum prazo nos próximos 14 dias. ✅")
        return

    lines = ["*Prazos próximos (14 dias):*\n"]
    for p in deadlines:
        d = p["days_left"]
        emoji = "🚨" if d == 0 else "🔴" if d <= 1 else "🟡" if d <= 3 else "🟢"
        lines.append(f"{emoji} *{p['name']}* — {p['deadline']} ({d}d)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /projeto
# ---------------------------------------------------------------------------


async def projeto_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso:\n• `/projeto add <nome> [YYYY-MM-DD]`\n• `/projeto list`",
            parse_mode="Markdown",
        )
        return

    sub = args[0].lower()
    if sub == "list":
        await _projeto_list(update)
    elif sub == "add":
        await _projeto_add(update, args[1:])
    else:
        await update.message.reply_text(
            "Subcomandos disponíveis: `add`, `list`", parse_mode="Markdown"
        )


async def _projeto_list(update: Update) -> None:
    try:
        projects = list(
            Project.select()
            .where(Project.status == "active")
            .order_by(Project.created_at.desc())
        )
        if not projects:
            await update.message.reply_text(
                "Nenhum projeto ativo. Use `/projeto add` para criar um.",
                parse_mode="Markdown",
            )
            return

        lines = ["*Projetos Ativos:*\n"]
        for p in projects:
            dl = f"📅 {p.deadline}" if p.deadline else "sem prazo"
            lines.append(f"• `[{p.id}]` *{p.name}* — {dl}")
            if p.description:
                lines.append(f"  _{p.description}_")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        logger.error("Error listing projects", exc_info=True)
        await update.message.reply_text("Erro ao listar projetos.")


async def _projeto_add(update: Update, args: list[str]) -> None:
    if not args:
        await update.message.reply_text(
            "Informe pelo menos o nome do projeto.", parse_mode="Markdown"
        )
        return

    deadline: date | None = None
    name_parts: list[str] = []

    for arg in args:
        # Detect a date token (YYYY-MM-DD)
        if len(arg) == 10 and arg.count("-") == 2:
            try:
                deadline = datetime.strptime(arg, "%Y-%m-%d").date()
                continue
            except ValueError:
                pass
        name_parts.append(arg)

    name = " ".join(name_parts).strip()
    if not name:
        await update.message.reply_text("Informe o nome do projeto.")
        return

    try:
        project = Project.create(name=name, deadline=deadline)
        dl_str = f"Prazo: {deadline}" if deadline else "Sem prazo definido"
        await update.message.reply_text(
            f"✅ Projeto *{name}* criado (ID: `{project.id}`)\n{dl_str}",
            parse_mode="Markdown",
        )
    except Exception:
        logger.error("Error creating project", exc_info=True)
        await update.message.reply_text("Erro ao criar projeto.")


# ---------------------------------------------------------------------------
# /prazo
# ---------------------------------------------------------------------------


async def prazo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: `/prazo <id> <YYYY-MM-DD>`", parse_mode="Markdown"
        )
        return

    try:
        project_id = int(args[0])
    except ValueError:
        await update.message.reply_text("O ID do projeto deve ser um número.")
        return

    try:
        new_deadline = datetime.strptime(args[1], "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text(
            "Formato de data inválido. Use `YYYY-MM-DD`.", parse_mode="Markdown"
        )
        return

    try:
        project = Project.get_by_id(project_id)
        project.deadline = new_deadline
        project.save()
        await update.message.reply_text(
            f"✅ Prazo de *{project.name}* atualizado para `{new_deadline}`",
            parse_mode="Markdown",
        )
    except Project.DoesNotExist:
        await update.message.reply_text("Projeto não encontrado.")
    except Exception:
        logger.error("Error updating deadline", exc_info=True)
        await update.message.reply_text("Erro ao atualizar prazo.")


# ---------------------------------------------------------------------------
# Session lifecycle helpers
# ---------------------------------------------------------------------------


async def _start_session(
    update: Update,
    session_type: str,
    initial_message: str,
    use_sonnet: bool = False,
) -> None:
    """Create a new AgentSession, send the first AI message, store in active_sessions."""
    user_id = update.effective_user.id
    ctx = build_context()
    session = AgentSession(session_type=session_type, context=ctx, use_sonnet=use_sonnet)

    extra = _SESSION_EXTRA.get(session_type, "")
    system = build_system_prompt(ctx)
    if extra:
        system = f"{system}\n\n{extra}"

    try:
        reply = await send_message(session, initial_message, system_prompt=system)
        active_sessions[user_id] = session
        await update.message.reply_text(reply)
    except Exception:
        logger.error("Error starting session '%s'", session_type, exc_info=True)
        await update.message.reply_text(
            "⚠️ Erro ao conectar com o agente. Verifique a `ANTHROPIC_API_KEY` e tente novamente.",
            parse_mode="Markdown",
        )


async def _close_session(update: Update, user_id: int) -> None:
    """Summarise and persist a session, then remove it from active_sessions."""
    session = active_sessions.pop(user_id, None)
    if not session:
        await update.message.reply_text("Nenhuma conversa ativa no momento.")
        return

    try:
        transcript = session.get_transcript()
        summary = await summarize_conversation(transcript)

        # Persist to the appropriate model
        if session.session_type == "decision":
            Decision.create(
                context=session.messages[0]["content"][:1000] if session.messages else "",
                conclusion=session.last_assistant_message()[:500],
                rationale=summary,
            )
        elif session.session_type in ("planning", "nightly_planning"):
            DailyPlan.create(
                date=date.today(),
                priorities=summary,
                raw_conversation=transcript,
            )

        Interaction.create(type=session.session_type, summary=summary)

        await update.message.reply_text(
            f"✅ Conversa encerrada e salva.\n\n_{summary}_",
            parse_mode="Markdown",
        )
    except Exception:
        logger.error("Error closing session", exc_info=True)
        await update.message.reply_text("Conversa encerrada (resumo não disponível).")


# ---------------------------------------------------------------------------
# /planejar, /decidir, /revisao
# ---------------------------------------------------------------------------


async def planejar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return
    await _start_session(update, "planning", "Preciso planejar meu dia.")


async def decidir_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return
    initial = " ".join(context.args) if context.args else "Preciso de ajuda para tomar uma decisão."
    await _start_session(update, "decision", initial, use_sonnet=True)


async def revisao_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return
    await _start_session(update, "weekly_review", "Vamos fazer a revisão semanal.")


# ---------------------------------------------------------------------------
# /fim  /cancel
# ---------------------------------------------------------------------------


async def fim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update.effective_user.id):
        return
    await _close_session(update, update.effective_user.id)


# ---------------------------------------------------------------------------
# Generic text message router
# ---------------------------------------------------------------------------


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route any plain text message to the user's active session."""
    if not _authorized(update.effective_user.id):
        return

    user_id = update.effective_user.id
    session = active_sessions.get(user_id)

    if not session:
        await update.message.reply_text(
            "Nenhuma conversa ativa. Use /planejar, /decidir ou /revisao para começar."
        )
        return

    try:
        reply = await send_message(session, update.message.text)
        await update.message.reply_text(reply)
    except Exception:
        logger.error("Error in message_handler", exc_info=True)
        await update.message.reply_text(
            "⚠️ Erro na comunicação. Tente novamente ou use /fim para encerrar."
        )
