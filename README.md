# Painel de Desempenho da Equipe — Koncluí (nuvem)

Robô gratuito (GitHub Actions) que, **toda madrugada (04h Brasília)**, faz login no Koncluí,
lê o dashboard do **mês vigente** e publica o **Painel de Desempenho da Equipe** no GitHub Pages —
sem depender do PC do Ivan.

## Como funciona
- `gerar_painel.py` — login (Playwright/Chromium), lê ranking por colaborador e por setor + KPIs do mês, gera `site/index.html`.
- `.github/workflows/atualizar.yml` — agenda `0 7 * * *` (UTC) = 04h Brasília; também roda manualmente (workflow_dispatch). Publica no Pages.
- Mostra só desempenho (% de execução), **sem valores em R$**. Cores = faixas do prêmio (verde ≥90, âmbar 80–89, cinza <80), meta 90%.

## Segredos necessários (Settings → Secrets and variables → Actions)
- `KONCLUI_EMAIL` — e-mail de login do Koncluí
- `KONCLUI_SENHA` — senha do Koncluí

> O painel reflete o **mês atual** (muda sozinho na virada do mês). Sem custo: Actions + Pages no plano free.
