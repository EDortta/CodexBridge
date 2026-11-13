# Evidência — `workspace_binding_required:codexbridge:devel3`

Data do incidente: 13/11/2026, 17:49 (America/Sao_Paulo), conforme relato
operacional.

## Diagnóstico

O erro é produzido exclusivamente por
`require_active_node_project_authorization()` quando não existe uma linha em
`workspace_bindings` para o par `(node_id, project_id)`. Portanto, o incidente
prova falta de provisionamento do binding para `codexbridge/devel3` (ou uma
divergência de identificadores); ele acontece antes da leitura de
`project_authorizations`. O erro, sozinho, não prova se a autorização está
ausente ou revogada.

O snapshot MCP versionado nesta coleta confirma que o Agent/Executor `devel3`
estava conhecido e conectado (`logs/mcp-recordings/20261113T201211Z/`), logo a
falha observada não é, primariamente, ausência de conexão do Agent. O Agent
continua exigindo sua própria allowlist local; isso deve ser verificado como
segunda etapa do provisionamento.

O `codex_bridge.db` deste checkout não é uma cópia confiável da produção: a
consulta somente-leitura encontrou `codexbridge-demo`, nenhum nó com nome
`devel3`, zero `workspace_bindings` e zero `project_authorizations`. Esses
dados não foram usados para alterar configuração nem para afirmar o estado
atual da produção.

O log de produção fornecido confirma o mesmo diagnóstico e identifica o ponto
exato da falha:

```text
2026-11-13T17:49:48-0300 ... POST /mcp HTTP/1.1 500 Internal Server Error
... gateway/app/main.py:746 in mcp_endpoint
... gateway/app/mcp/server.py:792 in handle_mcp_call
... gateway/app/services/store.py:766 in create_task
... gateway/app/services/store.py:549 in require_active_node_project_authorization
ValueError: workspace_binding_required:codexbridge:devel3
```

A linha anterior `17:49:47 ... POST /mcp ... 202 Accepted` é compatível com
uma notificação MCP sem `id`; ela não representa sucesso da tarefa. O `500`
seguinte é a chamada com resultado que tentou criar a tarefa.

## Evidência do transporte

Antes da correção, o endpoint chamava `handle_mcp_call()` sem tratar a
`ValueError` de autorização; o Starlette a convertia em HTTP 500. A correção
mantém o fail-closed e retorna um erro JSON-RPC estruturado, por exemplo:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32000,
    "message": "workspace_binding_required:codexbridge:devel3",
    "data": {
      "code": "workspace_binding_required",
      "detail": "workspace_binding_required:codexbridge:devel3",
      "context": "codexbridge:devel3"
    }
  }
}
```

Erros de ferramenta continuam com HTTP 200 e erro JSON-RPC; falhas de
autenticação preservam seu status HTTP e passam a ter corpo JSON-RPC. Nenhum
path de disco é retornado.

## Testes determinísticos

Comando executado:

```text
pytest -q tests/integration/test_mcp_transport.py tests/integration/test_start_development_task.py
```

Resultado: **39 passed**, com apenas dois avisos existentes de depreciação do
FastAPI (`on_event`). A suíte cobre, no domínio, binding ausente, binding
inativo, autorização revogada e capacidade insuficiente; a suíte MCP cobre os
quatro motivos no transporte e uma falha de configuração `409`, confirmando
que nenhum deles retorna HTTP 500.

## Procedimento oficial de provisionamento — não executado

Este procedimento exige aprovação humana para cada escrita. O Agent não cria
binding nem autorização; descoberta não é autorização.

1. Fazer somente preflight no gateway, confirmando os IDs reais:

   ```bash
   BASE='https://codexbridge.inovacaosistemas.com.br'
   AUTH_HEADER="Authorization: Bearer $CODEXBRIDGE_ADMIN_TOKEN"
   curl --fail-with-body -H "$AUTH_HEADER" "$BASE/api/v1/nodes"
   curl --fail-with-body -H "$AUTH_HEADER" "$BASE/api/v1/projects"
   curl --fail-with-body -H "$AUTH_HEADER" \
     "$BASE/api/v1/nodes/devel3/discovered-resources?state=discovered"
   ```

2. Se houver candidato descoberto que corresponda ao workspace de
   `codexbridge`, revisar manualmente `resourcePath`, `rootPath`, remote e
   projeto. Só depois da aprovação, adotar o candidato:

   ```bash
   curl --fail-with-body -X POST \
     -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
     -H 'Idempotency-Key: <valor-novo-e-estavel>' \
     "$BASE/api/v1/discovered-resources/<resource-id>/adopt" \
     --data '{"projectId":"codexbridge","grantCapabilities":[]}'
   ```

   Essa chamada cria/reusa o projeto e cria o `WorkspaceBinding`; com lista
   vazia ela não concede capacidades.

3. Depois de confirmar o binding e a identidade do nó, conceder somente a
   capacidade necessária pela rota administrativa separada. Para uma tarefa
   `analyze`, começa-se por `read`; `modify` só pode ser concedido com
   aprovação explícita para execução de escrita:

   ```bash
   curl --fail-with-body -X POST \
     -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
     "$BASE/api/v1/nodes/devel3/projects/codexbridge/authorize" \
     --data '{"capabilities":["read"]}'
   ```

4. Verificar no banco/Control, sem expor `local_path` ao cliente MCP, que o
   binding está `active`, a autorização não tem `revoked_at` e as capacidades
   cobrem o modo solicitado. Verificar também, no Agent, a allowlist local do
   projeto e o path real. A configuração do gateway e a allowlist do Agent
   devem permanecer sincronizadas; reinício/deploy não faz parte deste
   procedimento e requer aprovação separada.

5. Repetir a chamada MCP em `mode="analyze"` e guardar a resposta e o
   `requestId` como evidência. Para `implement`, repetir o preflight de
   autorização com `modify`; nunca elevar a capacidade só para fazer o erro
   desaparecer.

## Escopo desta correção

Alterado apenas o tratamento do transporte em `gateway/app/main.py` e seus
testes em `tests/integration/test_mcp_transport.py`. Nenhuma configuração de
produção, banco remoto, binding ou autorização foi criada, alterada, revogada,
reiniciada ou publicada.
