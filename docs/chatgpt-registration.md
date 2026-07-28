# Registrar no ChatGPT

Confirmado com documentação oficial consultada em `2026-07-28`:

* o ChatGPT Developer mode aceita apps criados a partir de MCP remoto;
* a URL pública deve incluir o endpoint MCP, por exemplo `https://codexbridge.inovacaosistemas.com.br:8443/mcp`;
* para este projeto, o modo correto é `OAuth`.

## Passos

1. No ChatGPT web, abrir `Settings -> Security and login`.
2. Ativar `Developer mode`.
3. Abrir `ChatGPT Plugins`.
4. Criar um app em modo desenvolvedor apontando para `https://codexbridge.inovacaosistemas.com.br:8443/mcp`.
5. Escolher `OAuth` como autenticação.
6. Concluir o login na tela do `gateway`.
7. Revisar ferramentas descobertas.
8. Em nova conversa, habilitar o app na composição.

## Próximo documento

Para rollout multiusuário com OAuth, ver [chatgpt-oauth-rollout.md](./chatgpt-oauth-rollout.md).
