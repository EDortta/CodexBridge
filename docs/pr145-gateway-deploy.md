# Implantação controlada do Gateway: PR #145

O Gateway foi reiniciado em 27/11/2026, mas um único curl imediatamente após o restart
encontrou a porta 18080 ainda indisponível e disparou rollback. Isso não prova
falha de inicialização: apenas ausência de readiness no instante da checagem.

## Procedimento único

Execute em devel3, em um worktree que contenha o merge do PR #145 e os scripts
desta entrega. O script confere o SHA dos dois módulos contra valores imutáveis
e só aplica com a opção explícita --apply.

    cd /home/esteban/Sync/Projects/AI/CodexBridge-agent
    git fetch origin development
    git worktree add --detach /tmp/codexbridge-pr145-deploy origin/development
    cd /tmp/codexbridge-pr145-deploy
    python3 scripts/deploy_pr145_gateway_with_evidence.py --apply

O comando prepara um diretório privado em frida via SSH/SCP e executa
sudo interativo; nenhuma senha ou token é armazenado.

## Contrato

- Arquivos autorizados: somente gateway/app/services/agent_hub.py e store.py.
- Pré-validação: SHA-256 de origem e destino, sintaxe, serviço ativo e /health.
- Se já estiver atualizado: already_current, sem restart.
- Se o baseline divergir: bloqueio sem alteração.
- Antes de aplicar: backup dos dois módulos em /var/backups/codexbridge.
- Aplicação: substituição atômica preservando permissões e ownership.
- Readiness: até 75 segundos, usando systemctl e HTTP /health.
- Se falhar: diagnóstico journalctl apenas local; rollback dos dois arquivos,
  restart e verificação da saúde restaurada.
- Manifesto sanitizado: publisher.py enqueue --file e flush, com confirmação
  exata da linha published=<caminho>.
- Status de sucesso só quando deploy e publicação de evidências estiverem confirmados.
- Sem logs brutos, tokens, segredos ou caminhos privados no repositório de evidências.

## Testes

    python3 -m pytest -q tests/unit/test_pr145_gateway_deploy.py

Os testes usam arquivos temporários e mocks; não reiniciam o Gateway.

**Atenção:** esse deploy não substitui a homologação real da reconexão do Agent.
Depois da atualização do Gateway e do Agent, repetir a interrupção com requestId
novo e exigir resultado terminal interrupted, reconexão e nenhuma segunda execução.
