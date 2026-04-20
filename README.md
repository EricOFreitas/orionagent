# Orion — Agente de Produtividade Pessoal

Bot de Telegram em Python que atua como agente de produtividade inteligente. Usa a API da Anthropic para raciocínio, planejamento e apoio a decisões. Persiste dados em SQLite via Peewee e agenda tarefas com APScheduler.

---

## Funcionalidades

| Funcionalidade | Descrição |
|---|---|
| **Ritual matinal** | Mensagem diária automática com check-in de energia, compromissos e foco. Gera plano do dia com 3 prioridades. |
| **Planejamento do dia** | Sessão conversacional guiada (`/planejar`) com contexto de projetos e prazos. |
| **Gestão de projetos** | `/projeto add/list` e `/prazo` para cadastrar e acompanhar projetos com prazos. |
| **Alertas de prazo** | Notificações automáticas 7, 3, 1 e 0 dias antes do vencimento. |
| **Modo decisão** | `/decidir` usa Claude Sonnet para raciocínio estruturado. Decisão e racional são salvos no banco. |
| **Revisão semanal** | Revisão guiada automática (semanal) com resumo de projetos e decisões da semana. |

---

## Requisitos

- Python 3.11+
- Conta na [Anthropic Console](https://console.anthropic.com/) com créditos
- Bot do Telegram criado via [@BotFather](https://t.me/BotFather)
- Seu Chat ID do Telegram (obtenha via [@userinfobot](https://t.me/userinfobot))

---

## Setup local

### 1. Clone e configure o ambiente

```bash
git clone <repo-url>
cd orion
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure as variáveis de ambiente

```bash
cp .env.example .env
```

Edite o arquivo `.env` com seus valores reais:

| Variável | Obrigatória | Descrição |
|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | Token do bot (BotFather) |
| `ANTHROPIC_API_KEY` | ✅ | Chave da API Anthropic |
| `USER_CHAT_ID` | ✅ | Seu Chat ID do Telegram |
| `TIMEZONE` | — | Fuso horário IANA (padrão: `America/Sao_Paulo`) |
| `MORNING_RITUAL_TIME` | — | Horário do ritual (padrão: `07:00`) |
| `WEEKLY_REVIEW_DAY` | — | Dia da revisão semanal: `monday` ou `sunday` (padrão: `monday`) |
| `DATABASE_PATH` | — | Caminho do banco SQLite (padrão: `data/orion.db`) |

### 3. Execute

```bash
python main.py
```

O banco de dados é criado automaticamente na primeira execução.

---

## Comandos do bot

```
/start              — Lista todos os comandos disponíveis
/status             — Prazos nos próximos 14 dias
/planejar           — Inicia sessão de planejamento do dia
/decidir [contexto] — Inicia modo decisão (Claude Sonnet)
/revisao            — Inicia revisão semanal
/fim                — Encerra a conversa ativa e salva o resumo
/projeto add <nome> [YYYY-MM-DD]  — Cria novo projeto
/projeto list       — Lista projetos ativos
/prazo <id> <YYYY-MM-DD>          — Atualiza prazo de um projeto
```

---

## Deploy com Docker

### Build e execução local

```bash
docker build -t orion-bot .

docker run -d \
  --name orion \
  --restart unless-stopped \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  orion-bot
```

O volume `-v $(pwd)/data:/app/data` persiste o banco SQLite fora do container.

---

## Deploy no Coolify (VPS com CyberPanel)

### Pré-requisitos

- Coolify instalado e acessível
- Repositório Git com o código (GitHub, GitLab, Gitea etc.)

### Passo a passo

1. **No Coolify**, crie um novo serviço → *Application* → conecte seu repositório.

2. **Build Pack**: selecione **Dockerfile** (o `Dockerfile` na raiz será detectado automaticamente).

3. **Variáveis de Ambiente**: na aba *Environment Variables*, adicione todas as variáveis do `.env.example` com seus valores reais.

4. **Volumes persistentes**: adicione um volume para o banco de dados:
   - Source (host): um path persistente em sua VPS, ex: `/data/orion`
   - Destination (container): `/app/data`

5. **Network mode**: o bot usa long-polling, não precisa de porta exposta. Deixe sem port mapping.

6. Clique em **Deploy**. O Coolify fará o build e iniciará o container.

### Atualizações

Push para a branch configurada dispara um novo deploy automaticamente (webhook do Coolify).

---

## Arquitetura

```
orion/
├── main.py                  # Entry point: init DB, register handlers, start scheduler
├── settings.py              # Variáveis de ambiente e constantes
├── requirements.txt
├── Dockerfile
├── .env.example
│
├── bot/
│   ├── agent.py             # Chamadas à API Anthropic; gerencia AgentSession
│   ├── context_builder.py   # Lê o banco e monta o contexto para o system prompt
│   ├── handlers.py          # Handlers de comandos Telegram; active_sessions dict
│   └── scheduler.py         # Jobs APScheduler (ritual, alertas, revisão)
│
├── db/
│   └── models.py            # Modelos Peewee: Project, DailyPlan, Decision, Interaction, Settings
│
├── prompts/
│   └── system.py            # System prompts por funcionalidade
│
└── data/                    # SQLite database (criado em runtime)
```

### Roteamento de modelos

| Situação | Modelo |
|---|---|
| Ritual matinal, Planejamento, Revisão semanal, Alertas | `claude-haiku-4-5` |
| `/decidir` (decisões complexas) | `claude-sonnet-4-5` |
| Resumo de conversa (persistência) | `claude-haiku-4-5` |

### Gestão de sessões

Todas as conversas multi-turno são mantidas em memória no dict `active_sessions` (em `handlers.py`), compartilhado com o scheduler. Ao encerrar com `/fim`, a conversa é resumida pela API e salva no banco como `Interaction` (e como `DailyPlan` ou `Decision` conforme o tipo).

---

## Notas de segurança

- O bot só responde ao `USER_CHAT_ID` configurado — todas as outras mensagens são silenciosamente ignoradas.
- Nunca commite o arquivo `.env`. Ele já está no `.gitignore`.
- Em produção, armazene segredos nas variáveis de ambiente do Coolify, nunca no repositório.
