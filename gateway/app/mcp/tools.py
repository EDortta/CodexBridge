from __future__ import annotations

from typing import Any


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "executor_status",
            "title": "Executor status",
            "description": "Consultar se um executor especifico esta online e apto a receber tarefas.",
            "inputSchema": {
                "type": "object",
                "properties": {"executor_id": {"type": "string"}},
                "required": ["executor_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_executors",
            "title": "List executors",
            "description": "Listar executores autorizados e seus estados recentes.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "list_projects",
            "title": "List projects",
            "description": "Listar projetos autorizados para um executor.",
            "inputSchema": {
                "type": "object",
                "properties": {"executor_id": {"type": "string"}},
                "required": ["executor_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "submit_codex_task",
            "title": "Submit Codex task",
            "description": "Criar uma tarefa para o Codex CLI em um projeto autorizado.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "executor_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "instruction": {"type": "string"},
                    "mode": {"type": "string", "enum": ["analyze", "review", "edit", "test", "implement"]},
                    "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 86400},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "run_when_available": {"type": "boolean"},
                    "expires_at": {"type": "string", "format": "date-time"},
                },
                "required": [
                    "executor_id",
                    "project_id",
                    "instruction",
                    "mode",
                    "timeout_seconds",
                    "priority",
                    "run_when_available",
                    "expires_at",
                ],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_task_status",
            "title": "Get task status",
            "description": "Consultar o estado atual de uma tarefa.",
            "inputSchema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_task_logs",
            "title": "Get task logs",
            "description": "Consultar logs incrementais de uma tarefa.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_task_result",
            "title": "Get task result",
            "description": "Consultar resultado estruturado, diff e testes de uma tarefa.",
            "inputSchema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "continue_codex_session",
            "title": "Continue Codex session",
            "description": "Criar uma nova tarefa que continue uma sessao anterior do Codex.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "instruction": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 86400},
                },
                "required": ["task_id", "instruction", "timeout_seconds"],
                "additionalProperties": False,
            },
        },
        {
            "name": "cancel_codex_task",
            "title": "Cancel Codex task",
            "description": "Cancelar uma tarefa em fila ou em execucao.",
            "inputSchema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "approve_codex_task",
            "title": "Approve Codex task",
            "description": "Aprovar ou rejeitar uma tarefa sensivel em aguardando aprovacao.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["approved", "rejected"]},
                    "reason": {"type": "string"},
                },
                "required": ["task_id", "decision"],
                "additionalProperties": False,
            },
        },
        {
            "name": "start_development_task",
            "title": "Start development task",
            "description": (
                "Ponto de entrada conversacional: 'resolva a issue X do projeto Y'. "
                "Resolve o projeto por id, nome ou prefixo unico; resolve o executor "
                "automaticamente quando omitido; calcula expires_at sozinho; e devolve uma "
                "estimativa de duracao baseada no historico. Sem path de disco: o projeto "
                "e sempre um project_id, nunca um caminho."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "project_id, nome, ou prefixo unico de um dos dois (retornado por list_projects).",
                    },
                    "issue": {
                        "type": "string",
                        "description": (
                            "Numero da issue (ex '57' ou 'docs:57'), 'local:<id>' para uma issue "
                            "cadastrada neste gateway, ou 'gh:<n>' (ainda nao suportado -- "
                            "ingestao de issue do GitHub nao tem dono neste sistema)."
                        ),
                    },
                    "request": {
                        "type": "string",
                        "maxLength": 8000,
                        "description": "O pedido do operador, nas proprias palavras. Se omitido, precisa de 'issue'.",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["claude", "codex", "cursor-agent", "gemini", "opencode", "aider"],
                        "default": "claude",
                    },
                    "executor_id": {"type": "string", "description": "Omitido: escolhido automaticamente entre os executores autorizados para o projeto."},
                    "mode": {"type": "string", "enum": ["analyze", "review", "edit", "test", "implement"], "default": "implement"},
                    "branch": {
                        "type": "string",
                        "description": "Branch de entrega (ex 'development' ou 'feature/uc-57/...'). Obrigatorio se allow_push=true.",
                    },
                    "allow_push": {
                        "type": "boolean",
                        "default": False,
                        "description": "Pre-autoriza commit e push nessa branch ao final da tarefa. Exige escopo de aprovacao.",
                    },
                    "base_branch": {"type": "string", "default": "development"},
                    "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 86400, "default": 3600},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"},
                    "run_when_available": {"type": "boolean", "default": True},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
        },
        {
            "name": "bind_project_forge",
            "title": "Bind project to a forge repository",
            "description": (
                "Declarar (ou confirmar) a qual repositorio GitHub um projeto esta ligado. "
                "So um humano com escopo de administrador pode chamar esta ferramenta -- ela "
                "e o que liga o roteamento de forge para as outras ferramentas de issue. "
                "O executor confirma o remote real antes de cada operacao; isto so registra "
                "o que foi declarado."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "project_id, nome, ou prefixo unico."},
                    "repo_identity": {
                        "type": "string",
                        "description": "owner/repo no GitHub, ex 'acme/widgets'.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "true confirma que este e o repositorio correto (confidence vira "
                            "'confirmed'); false apenas declara a intencao ('declared')."
                        ),
                    },
                },
                "required": ["project", "repo_identity"],
                "additionalProperties": False,
            },
        },
        {
            "name": "create_project_issue",
            "title": "Create a project issue",
            "description": (
                "Criar uma issue no projeto. Se o projeto estiver ligado a um repositorio GitHub "
                "(bind_project_forge), isto cria uma operacao de forge (issue_open) que espera "
                "decisao humana na Central de Decisoes antes de publicar no GitHub. Se nao "
                "estiver ligado, cria uma issue local imediatamente, sem aprovacao. O operador "
                "usa a mesma frase nos dois casos."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 256},
                    "body": {"type": "string", "maxLength": 65536},
                    "executor_id": {
                        "type": "string",
                        "description": "Omitido: escolhido automaticamente (so relevante quando ligado ao forge).",
                    },
                },
                "required": ["project", "title"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_project_issues",
            "title": "List project issues",
            "description": (
                "Listar issues do projeto. Ligado ao forge: despacha uma leitura (issue_list) "
                "ao GitHub via o executor, sem aprovacao (e uma leitura). Nao ligado: le as "
                "issues locais deste gateway. Mesma ferramenta, mesmos argumentos, nos dois casos."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "state": {"type": "string", "description": "Filtro de estado (ex 'open', 'closed', 'done')."},
                    "executor_id": {"type": "string"},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
        },
        {
            "name": "comment_project_issue",
            "title": "Comment on a project issue",
            "description": (
                "Comentar numa issue do GitHub. So funciona em projeto ligado ao forge "
                "(bind_project_forge) -- este gateway nao tem conceito de comentario em issue "
                "local. Cria uma operacao de forge (issue_comment) que espera decisao humana na "
                "Central de Decisoes."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "issue": {"type": "integer", "minimum": 1, "description": "Numero da issue no GitHub."},
                    "body": {"type": "string", "minLength": 1, "maxLength": 65536},
                    "executor_id": {"type": "string"},
                },
                "required": ["project", "issue", "body"],
                "additionalProperties": False,
            },
        },
        {
            "name": "close_project_issue",
            "title": "Close a project issue",
            "description": (
                "Fechar uma issue do projeto. Ligado ao forge: cria uma operacao de forge "
                "(issue_close) que espera decisao humana na Central de Decisoes. Nao ligado: "
                "marca a issue local como concluida imediatamente. Mesma ferramenta nos dois "
                "casos; o campo 'issue' e o numero da issue no GitHub quando ligado, ou o id da "
                "issue local quando nao."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "issue": {"type": "string", "description": "Numero (GitHub) ou id (local) da issue."},
                    "executor_id": {"type": "string"},
                },
                "required": ["project", "issue"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_recent_tasks",
            "title": "List recent tasks",
            "description": "Listar tarefas recentes para auditoria e acompanhamento.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "states": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "queued", "waiting_executor", "awaiting_approval", "pausing",
                                "paused", "resuming", "restarting", "running", "completed",
                                "failed", "cancelled", "expired", "lost",
                            ],
                        },
                        "description": "Filtra por estado. Util para 'o que terminou desde a ultima vez que perguntei' (ex: [\"completed\", \"failed\"]).",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "create_reminder",
            "title": "Create reminder",
            "description": (
                "Criar um lembrete no Google Calendar do operador. O horario deve ser calculado "
                "por voce (o modelo) e enviado como data-hora ISO 8601, de preferencia com fuso "
                "explicito -- o servidor NAO interpreta frases como 'amanha' ou 'sexta que vem'. "
                "O servidor devolve o horario resolvido para voce confirmar em voz alta com o "
                "operador antes de dar a tarefa como concluida."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "O que lembrar, em uma linha. Vira o titulo do evento.",
                    },
                    "when": {
                        "type": "string",
                        "format": "date-time",
                        "description": (
                            "Instante do lembrete, ISO 8601, de preferencia com offset "
                            "(ex 2026-09-04T15:00:00-03:00). Sem offset, assume America/Sao_Paulo."
                        ),
                    },
                    "notes": {"type": "string", "maxLength": 4000},
                    "lead_minutes": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 40320,
                        "default": 0,
                        "description": "Quantos minutos antes de 'when' o alerta dispara. 0 = na hora.",
                    },
                    "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                "required": ["text", "when"],
                "additionalProperties": False,
            },
        },
        {
            "name": "cancel_reminder",
            "title": "Cancel reminder",
            "description": "Cancelar um lembrete previamente criado.",
            "inputSchema": {
                "type": "object",
                "properties": {"reminder_id": {"type": "string", "minLength": 1, "maxLength": 1024}},
                "required": ["reminder_id"],
                "additionalProperties": False,
            },
        },
    ]
