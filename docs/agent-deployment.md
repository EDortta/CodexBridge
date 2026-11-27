# Deploy canônico do Agent em devel3 (issue #149)

## Objetivo

Atualizar o Agent do PR #145 sem trocar o worktree autorizado:
`feature/file-instruction-ws-bridge` em `CodexBridge-agent`.
O serviço do usuário carrega `agent.codex_bridge_agent.service` pelo
venv em `~/.local/share/codex-bridge/.venv`, com WorkingDirectory
definido por override e configuração do file executor fixando root e branch.

## Interface operacional

Rodar em um checkout aprovado da development que contenha estes scripts:

    cd /tmp/codexbridge-issue147
    git fetch origin development
    # Após merge desta implementação, criar checkout atualizado e limpo
    python3 scripts/deploy_agent.py --check
    python3 scripts/deploy_agent.py --apply

O comando imprime DEPLOY_ID antes de iniciar qualquer operação em segundo
plano. Uma unidade temporária `systemd-run --user` executa a troca de código
e o reinício do Agent, independentemente da vida do terminal.

Se fechar o terminal, NÃO repetir --apply:

    python3 scripts/deploy_agent.py --resume ag-YYYYMMDDTHHMMSSZ-xxxxxxxx

Consultar estado local sem reiniciar:

    python3 scripts/deploy_agent.py --status ag-YYYYMMDDTHHMMSSZ-xxxxxxxx

## Segurança e limites

- Preflight de versão, branch, worktree limpo, unit efetiva, MainPID, cwd,
  root/branch no arquivo de configuração do executor, assinatura do código
  carregado e correspondência da versão de origem.
- Atualiza APENAS file_executor.py e file_ws_adapter.py. Nenhuma migração,
  arquivo de configuração, allowlist, dependência de venv ou Gateway muda.
- A alteração vira commit local na mesma branch feature, preservando a
  configuração do Agent. Esse commit local NÃO é enviado automaticamente.
- Rollback usa `git revert` (não `reset --hard`) e novo restart do serviço;
  o resultado fica em recibo local imutável, consultável por ID.
- Um lock local impede deploys concorrentes. Se o processo foi interrompido
  antes de gravar recibo, o estado fica pendente; não tentar novo apply.
- O publicador oficial grava apenas SHA256, commit, estado e rollback no
  development-evidences. Os logs privados não são publicados.
- O status de saúde do worker prova reinício com PID novo, não handshake
  WebSocket nem processamento de instrução. Exigir teste funcional separado.
- Esta primeira versão foi desenhada para o par de módulos PR145; novas
  versões precisam de um manifesto/contrato ampliado antes de deploy.

## Critério de homologação

Após CI verde, teste de pré-validação, aplicação via script, verificação
do release commit e comprovante imutável, confirmar pelo Gateway que o
executor se reconectou. Submeter tarefa nova e provocar interrupção do
Agent durante execução: recibo terminal interrupted, nenhuma repetição.
Somente então concluir o PR #145.
