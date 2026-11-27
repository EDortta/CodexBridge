# Implantação do Gateway no frida — comando canônico (#147)

**Única entrada operacional suportada:** `scripts/deploy_gateway.py`.
Não escolha scripts por número de PR. As rotinas de OAuth, staged-release
e PR145 são legadas e não devem ser utilizadas para novas implantações.

## Início

Em um worktree limpo do commit aprovado contendo o manifesto de release:

    cd /home/esteban/Sync/Projects/AI/CodexBridge-agent
    git fetch origin development
    git worktree add --detach /tmp/codexbridge-gateway-release origin/development
    cd /tmp/codexbridge-gateway-release
    python3 scripts/deploy_gateway.py --check
    python3 scripts/deploy_gateway.py --apply

O comando imprime `DEPLOY_ID` **antes** de efetuar qualquer operação remota.
Copie esse ID ou leia o registro em `~/.local/state/codexbridge/gateway-deploy/jobs`.

Se o console fechar ou perder conexão, **não aplique novamente**:

    cd /tmp/codexbridge-gateway-release
    python3 scripts/deploy_gateway.py --resume gw-YYYYMMDDTHHMMSSZ-xxxxxxxx

Para ler apenas o histórico local:

    cd /tmp/codexbridge-gateway-release
    python3 scripts/deploy_gateway.py --status gw-YYYYMMDDTHHMMSSZ-xxxxxxxx

## Modelo de segurança

- `--check` é a operação padrão; `--apply` exige intenção explícita.
- Fonte: `deploy/gateway-release.json`, manifesto de hashes versionado.
- Perfil inicial: `code-only` (sem banco/migração). Outros perfis são recusados.
- Escopo: somente arquivos declarados em `gateway/`; baseline e destino
  devem corresponder exatamente ao manifesto. Misturas ou desvios bloqueiam.
- Execução do worker remoto em um serviço transitório `systemd-run`; ele não
  depende da sessão SSH/TTY ou do processo local para terminar.
- Sudo: tenta autorização já válida com `sudo -n`; caso necessário,
  solicita a senha no terminal local e a passa pelo stdin de SSH sem PTY,
  sem gravar ou passar por argv, logs ou variáveis de ambiente.
- O worker faz backup privado, substituição de arquivos por rename atômico,
  restart, polling de `/health` e rollback com novo health check.
- O recibo remoto é persistido em diretório de staging com permissão privada,
  enquanto os logs de diagnóstico permanecem exclusivamente no frida.
- Reexecução da entrada `--resume` apenas consulta o recibo já existente;
  nunca dispara outro deploy.
- O publicador existente `publisher.py` é usado para publicar um manifesto
  sanitizado em development-evidences. Falha de publicação permanece pendente
  para nova tentativa com `--resume`.

## Limites explícitos

Esta primeira versão cobre deploy code-only e desconexão do console.
Não autoriza migrações de banco, não trata falha elétrica durante aplicação
e não garante rollback transacional de múltiplos arquivos se a máquina
perder energia entre renames. Esses casos exigem um perfil de release
separado com staging por diretório, controle de versão e rollback próprio.

Não usar `--apply` antes do CI e de uma revisão do mecanismo de segurança.
Depois do merge, repetir a aceitação do PR145 e confirmar hashes e
recibos reais, com evidência publicada.
