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

## Homologação de recuperação sem novo deploy (issue #149)

O `--apply` só aceita uma transição de versão; depois de uma implantação
bem-sucedida, deve bloquear novas aplicações com os mesmos arquivos.
Para não reimplantar o Agent apenas para testar o cliente desconectado:

1. Rodar o teste determinístico em que um processo separado grava o recibo
   enquanto o cliente está ausente. O `--resume` reconstitui o estado sem
   chamar `systemd-run` nem reiniciar o worker.
2. Validar a recuperação do deployment REAL já publicado: o verificador
   captura PID, HEAD, hashes dos dois módulos e SHA-256 do recibo e do job,
   chama `--resume` e exige que todas as observações permaneçam idênticas.
3. Executar com o publicador de evidências para registrar PASS/FAIL. Não
   publicar segredos nem logs brutos.

Exemplo no checkout de `development` atualizado que contenha o verificador:

```bash
cd /tmp/codexbridge-agent-recovery
python3 scripts/run_file_ws_evidence.py \
  --feature agent-deploy-recovery --timeout 60 -- \
  python3 scripts/verify_agent_deploy_resume.py \
  --deploy-id ag-20261127T181509Z-52d0af5a
```

Este procedimento não reinicia o Agent. Ele demonstra (a) que um cliente
que perdeu a resposta pode recuperar um recibo persistido sem reiniciar o
worker em teste determinístico e (b) que `--resume` de uma implantação
bem-sucedida não causa alterações no ambiente real.

**Limite de evidência:** não é um ensaio de matar um cliente durante um
deploy real *in progress*. Não declarar esse cenário homologado até haver
um candidato de release distinto e uma janela de implantação controlada.

### Teste real sem alteração no Agent: encerramento do cliente

O `scripts/probe_agent_detached_worker.py` cria um worker temporário
`systemd-run --user` que grava um recibo privado após breve atraso.
O orquestrador encerra intencionalmente **somente o processo cliente**
quando recebe o ACK de lançamento; prova então que o worker concluiu
independentemente dele. **Não altera a release, não reinicia o Agent,
não testa rollback nem representa uma implantação de produção.**

Executar pelo publicador oficial:

```bash
cd /tmp/codexbridge-agent-recovery
python3 scripts/run_file_ws_evidence.py \
  --feature agent-deploy-detach-probe --timeout 60 -- \
  python3 scripts/probe_agent_detached_worker.py
```

Resultados esperados: `CLIENT_TERMINATED=true`,
`DETACHED_WORKER=COMPLETED`, `AGENT_RESTARTED=false`,
`PROBE=PASS` no log privado; evidência sanitizada publicada
no `development-evidences`.

O teste não encerra o terminal do usuário: mata apenas o cliente filho
dedicado ao ensaio, sem efeitos sobre a sessão do operador.
