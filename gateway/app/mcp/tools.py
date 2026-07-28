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
            "name": "list_recent_tasks",
            "title": "List recent tasks",
            "description": "Listar tarefas recentes para auditoria e acompanhamento.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
                "additionalProperties": False,
            },
        },
    ]
