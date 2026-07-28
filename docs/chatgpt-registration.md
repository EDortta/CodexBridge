# Registrar no ChatGPT

Confirmado com documentação oficial consultada em `2026-07-28`:

* o ChatGPT Developer mode aceita apps criados a partir de MCP remoto;
* a URL pública deve incluir o endpoint MCP, por exemplo `https://frida.inovacaosistemas.com.br:8443/mcp`.

## Passos

1. No ChatGPT web, abrir `Settings -> Security and login`.
2. Ativar `Developer mode`.
3. Abrir `ChatGPT Plugins`.
4. Criar um app em modo desenvolvedor apontando para `https://frida.inovacaosistemas.com.br:8443/mcp`.
5. Revisar ferramentas descobertas.
6. Em nova conversa, habilitar o app na composição.

## Observação atual

O repositório já exige bearer token no endpoint MCP. Para uso direto no ChatGPT, o caminho recomendado é concluir o adaptador OAuth na próxima fase e então registrar o app com autenticação suportada nativamente pelo produto.

