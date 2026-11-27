# PR #145 — Ensaio de interrupção ao vivo

**Escopo:** uma tarefa do perfil preaprovado `unit-tests`, com um requestId
novo, já encaminhada via MCP ao Agent `devel3`. Somente o Agent systemd do
usuário é reiniciado, durante o estado `.running`. Não altera Gateway nem
outras tarefas.

**Pré-condições:** Gateway e Agent do PR #145 implantados; serviço
`codex-bridge-agent.service` ativo, worktree autorizado, config do executor,
inbox privada e perfil `unit-tests` configurado.

Usar em um checkout atualizado com este script:

```bash
cd /tmp/codexbridge-pr145-acceptance
python3 scripts/run_file_ws_evidence.py \
  --feature pr145-live-interruption --live-markers --timeout 240 -- \
  python3 -u scripts/accept_pr145_interruption.py \
  --request-id pr145-accept-20261127-01 --timeout 100
```

O script imprime `ARMED=<requestId>`. **Somente depois de armado**, enviar
via MCP `submit_file_instruction` com:
```json
{"schemaVersion":1,"requestId":"pr145-accept-20261127-01","project":"codexbridge","branch":"feature/file-instruction-ws-bridge","profile":"unit-tests"}
```

Não iniciar segunda instância do Agent. O observer detecta exclusivamente
`<requestId>.running` e executa `systemctl --user restart
codex-bridge-agent.service`. Verifica `results/<requestId>.json`:
`status=failed,reason=interrupted`, hash idêntico ao original, marcador DONE,
PID alterado e serviço ativo. Resultado local tem `ACCEPTANCE=LOCAL_PASS`.

**Não é PASS end-to-end:** verificar separadamente via MCP
`get_task_status` e `get_task_result` do task_id retornado; deve terminar
`failed` com `reason=interrupted`. Repetir o MESMO requestId e confirmar
o MESMO recibo sem executar perfil novamente. Se ficar `running`, falhar
a reconciliação ou não houver recibo, investigar sem resubmeter como novo ID.

Os logs detalhados ficam locais e a evidência sanitizada do wrapper é
publicada em `development-evidences`. Um teste que não observar o estado
`.running` não reinicia o Agent: retorna falha sem efeito colateral.

## Correção após tentativa 2026-11-27

O wrapper original ocultava `ARMED` no log, impedindo o operador de
notificar o ChatGPT para enviar o pedido. Com `--live-markers`, somente
marcadores de controle predefinidos são exibidos em tempo real; a saída
bruta permanece privada. A branch destacada é registrada como `detached`,
nunca como campo vazio no caminho de evidência. Não reusar o requestId da
tentativa anterior.
