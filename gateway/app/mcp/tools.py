from __future__ import annotations

from typing import Any

from gateway.app.services.issue_types import EPIC_STATUSES, ISSUE_PRIORITIES, ISSUE_STATUSES


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
                "e o que direciona as demais ferramentas de issue para o repositorio GitHub "
                "certo. O executor confirma o remote real antes de cada operacao no GitHub; "
                "isto so registra o que foi declarado."
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
                "(bind_project_forge), isto pede ao executor a abertura da issue no GitHub -- "
                "nunca ao agente de codificacao, que nao tem acesso a rede --, e espera decisao "
                "humana na Central de Decisoes antes de publicar. Se nao estiver ligado, cria "
                "uma issue local imediatamente, sem aprovacao. O operador usa a mesma frase nos "
                "dois casos."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 256},
                    "body": {"type": "string", "maxLength": 65536},
                    "executor_id": {
                        "type": "string",
                        "description": "Omitido: escolhido automaticamente (so relevante quando ligado a um repositorio GitHub).",
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
                "Listar issues do projeto. Projeto ligado a um repositorio GitHub: despacha uma "
                "leitura ao GitHub via o executor, sem aprovacao (e uma leitura). Nao ligado: le "
                "as issues locais deste gateway. Mesma ferramenta, mesmos argumentos, nos dois "
                "casos."
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
                "Comentar numa issue do GitHub. So funciona em projeto ligado a um repositorio "
                "GitHub (bind_project_forge) -- este gateway nao tem conceito de comentario em "
                "issue local. O executor publica o comentario apos decisao humana na Central de "
                "Decisoes."
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
                "Fechar uma issue do projeto. Projeto ligado a um repositorio GitHub: o executor "
                "fecha a issue no GitHub apos decisao humana na Central de Decisoes. Nao ligado: "
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
            "name": "create_epic",
            "title": "Create epic",
            "description": "Criar uma epica para agrupar issues dentro de um projeto, ligado ou nao a um repositorio GitHub.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "project_id, nome, ou prefixo unico de um dos dois (retornado por list_projects).",
                    },
                    "title": {"type": "string", "minLength": 1, "maxLength": 255},
                    "description": {"type": "string", "maxLength": 20000},
                    "status": {"type": "string", "enum": sorted(EPIC_STATUSES)},
                    "idempotency_key": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Repetir a mesma chave devolve a mesma epica em vez de criar outra.",
                    },
                },
                "required": ["project", "title"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_epics",
            "title": "List epics",
            "description": "Listar epicas de um projeto, mais recentes primeiro.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "project_id, nome, ou prefixo unico de um dos dois (retornado por list_projects).",
                    },
                    "status": {"type": "array", "items": {"type": "string", "enum": sorted(EPIC_STATUSES)}},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
        },
        {
            "name": "update_epic",
            "title": "Update epic",
            "description": "Mudar titulo, descricao ou status de uma epica existente.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "epic_id": {"type": "string", "description": "id da epica (retornado por create_epic ou list_epics)."},
                    "title": {"type": "string", "minLength": 1, "maxLength": 255},
                    "description": {"type": "string", "maxLength": 20000},
                    "status": {"type": "string", "enum": sorted(EPIC_STATUSES)},
                    "expected_revision": {
                        "type": "integer",
                        "minimum": 1,
                        "description": (
                            "Revisao atual da epica (campo 'revision' de create_epic/list_epics). "
                            "Obrigatorio: protege contra sobrescrever uma mudanca concorrente."
                        ),
                    },
                },
                "required": ["epic_id", "expected_revision"],
                "additionalProperties": False,
            },
        },
        {
            "name": "create_issue",
            "title": "Create issue",
            "description": "Criar uma issue em um projeto, opcionalmente dentro de uma epica ja existente.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "project_id, nome, ou prefixo unico de um dos dois (retornado por list_projects).",
                    },
                    "epic_id": {"type": "string", "description": "id de uma epica existente no mesmo projeto (retornado por list_epics)."},
                    "title": {"type": "string", "minLength": 1, "maxLength": 255},
                    "description": {"type": "string", "maxLength": 20000},
                    "status": {"type": "string", "enum": sorted(ISSUE_STATUSES)},
                    "priority": {"type": "string", "enum": sorted(ISSUE_PRIORITIES)},
                    "labels": {"type": "array", "items": {"type": "string"}, "maxItems": 64},
                    "assignee_user_id": {"type": "string", "maxLength": 255},
                    "assignee_email": {"type": "string", "maxLength": 255},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 64,
                        "description": "ids de outras issues no mesmo projeto.",
                    },
                    "blocked_reason": {"type": "string", "maxLength": 20000},
                    "idempotency_key": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Repetir a mesma chave devolve a mesma issue em vez de criar outra.",
                    },
                },
                "required": ["project", "title"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_issues",
            "title": "List issues",
            "description": "Listar issues de um projeto, mais recentes primeiro, com filtros opcionais.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "project_id, nome, ou prefixo unico de um dos dois (retornado por list_projects).",
                    },
                    "status": {"type": "array", "items": {"type": "string", "enum": sorted(ISSUE_STATUSES)}},
                    "priority": {"type": "array", "items": {"type": "string", "enum": sorted(ISSUE_PRIORITIES)}},
                    "epic_id": {"type": "string"},
                    "assignee_user_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
        },
        {
            "name": "update_issue",
            "title": "Update issue",
            "description": (
                "Mudar status, prioridade, labels, assignee, dependencias ou motivo de bloqueio de "
                "uma issue existente. Para trocar a epica da issue, use move_issue_to_epic."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "id da issue, ou 'local:<id>' (os dois formatos sao aceitos).",
                    },
                    "title": {"type": "string", "minLength": 1, "maxLength": 255},
                    "description": {"type": "string", "maxLength": 20000},
                    "status": {"type": "string", "enum": sorted(ISSUE_STATUSES)},
                    "priority": {"type": "string", "enum": sorted(ISSUE_PRIORITIES)},
                    "labels": {"type": "array", "items": {"type": "string"}, "maxItems": 64},
                    "assignee_user_id": {"type": "string", "maxLength": 255},
                    "assignee_email": {"type": "string", "maxLength": 255},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 64,
                        "description": "Substitui o conjunto inteiro. ids de outras issues no mesmo projeto.",
                    },
                    "blocked_reason": {"type": "string", "maxLength": 20000},
                    "expected_revision": {
                        "type": "integer",
                        "minimum": 1,
                        "description": (
                            "Revisao atual da issue (campo 'revision' de create_issue/list_issues). "
                            "Obrigatorio: protege contra sobrescrever uma mudanca concorrente."
                        ),
                    },
                },
                "required": ["issue_id", "expected_revision"],
                "additionalProperties": False,
            },
        },
        {
            "name": "move_issue_to_epic",
            "title": "Move issue to epic",
            "description": (
                "Anexar (ou mover) uma issue para uma epica do mesmo projeto -- o unico mecanismo "
                "para trocar a epica de uma issue."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "id da issue, ou 'local:<id>' (os dois formatos sao aceitos).",
                    },
                    "epic_id": {"type": "string", "description": "id da epica de destino, no mesmo projeto da issue."},
                    "expected_revision": {
                        "type": "integer",
                        "minimum": 1,
                        "description": (
                            "Revisao atual da issue (campo 'revision' de create_issue/list_issues). "
                            "Obrigatorio: protege contra sobrescrever uma mudanca concorrente."
                        ),
                    },
                    "idempotency_key": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Repetir a mesma chave devolve o mesmo resultado em vez de mover de novo.",
                    },
                },
                "required": ["issue_id", "epic_id", "expected_revision"],
                "additionalProperties": False,
            },
        },
        {
            "name": "publish_epic_to_repo",
            "title": "Publish epic to repo",
            "description": (
                "Materializa uma epica e suas issues como arquivos markdown versionados no "
                "repositorio do proprio projeto (docs/issues/), via um executor conectado. Sem "
                "executor conectado autorizado para o projeto da epica, falha com erro tipado -- "
                "nunca enfileira silenciosamente. Republicar (a epica ja tem materialized_path) "
                "atualiza a pasta existente em vez de criar outra."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "epic_id": {"type": "string", "description": "id da epica (retornado por create_epic ou list_epics)."},
                    "executor_id": {
                        "type": "string",
                        "description": "Omitido: escolhido automaticamente entre os executores conectados que autorizam o projeto da epica.",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch de entrega para o commit (ex 'development'). Obrigatorio se allow_push=true.",
                    },
                    "allow_push": {
                        "type": "boolean",
                        "default": False,
                        "description": "Pre-autoriza commit e push nessa branch depois de escrever os arquivos. Exige escopo de aprovacao.",
                    },
                    "base_branch": {"type": "string", "default": "development"},
                    "commit_subject": {"type": "string", "maxLength": 200},
                },
                "required": ["epic_id"],
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
                            "Instante do lembrete, ISO 8601 e obrigatoriamente com offset "
                            "UTC (ex 2026-09-04T15:00:00-03:00). Sem offset a chamada e "
                            "recusada: quem chama sabe o fuso do operador, o gateway nao, e "
                            "um palpite errado dispara o lembrete na hora errada sem avisar."
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
