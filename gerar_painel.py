# -*- coding: utf-8 -*-
"""
Robo da nuvem (GitHub Actions): faz login no Konclui, le o dashboard do mes vigente
e gera site/index.html (Painel de Desempenho da Equipe). Sem custo, sem o PC do Ivan.
Credenciais vem dos secrets KONCLUI_EMAIL e KONCLUI_SENHA.
"""
import os, re, sys, json, datetime, pathlib, traceback
from playwright.sync_api import sync_playwright

EMAIL = os.environ.get("KONCLUI_EMAIL")
SENHA = os.environ.get("KONCLUI_SENHA")
if not EMAIL or not SENHA:
    print("ERRO: faltam os secrets KONCLUI_EMAIL / KONCLUI_SENHA.", file=sys.stderr)
    sys.exit(1)

BASE = pathlib.Path(__file__).parent
SITE = BASE / "site"; SITE.mkdir(exist_ok=True)
DEBUG = BASE / "debug"; DEBUG.mkdir(exist_ok=True)

MESES = ["janeiro","fevereiro","março","abril","maio","junho","julho","agosto",
         "setembro","outubro","novembro","dezembro"]
hoje = datetime.date.today()
primeiro = hoje.replace(day=1).isoformat()
periodo_label = f"{MESES[hoje.month-1].upper()} {hoje.year} (MÊS EM ANDAMENTO, ATÉ {hoje.strftime('%d/%m')}) · META 90%"

EXCLUIR = {"usuário geral", "usuario geral"}  # conta genérica fora do painel de pessoas

def parse_ranking(texto, inicio, fim):
    i = texto.find(inicio)
    if i == -1: return []
    seg = texto[i+len(inicio):]
    if fim:
        j = seg.find(fim)
        if j != -1: seg = seg[:j]
    linhas = [l.strip() for l in seg.splitlines() if l.strip()]
    out = []
    for k, l in enumerate(linhas):
        m = re.fullmatch(r"(\d{1,3})%", l)
        if m and k >= 1:
            nome = linhas[k-1]
            if re.fullmatch(r"\d{1,3}", nome):      # linha de rank, não é nome
                continue
            if len(nome) <= 3 and nome.isupper():   # iniciais de avatar (ex.: TS)
                continue
            out.append([nome, int(m.group(1))])
    return out

def kpi_apos(texto, label):
    i = texto.find(label)
    if i == -1: return None
    m = re.search(r"(\d[\d.]*)", texto[i+len(label):])
    return int(m.group(1).replace(".", "")) if m else None

def pct_do_total(texto, label):
    i = texto.find(label)
    if i == -1: return None
    m = re.search(r"(\d{1,3})%\s*do total", texto[i+len(label):])
    return int(m.group(1)) if m else None

def dump_erro(page, e):
    try:
        page.screenshot(path=str(DEBUG / "erro.png"), full_page=True)
        (DEBUG / "erro.html").write_text(page.content(), encoding="utf-8")
        (DEBUG / "erro.txt").write_text(f"{e}\nURL: {page.url}\n\n{traceback.format_exc()}", encoding="utf-8")
    except Exception:
        pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.set_default_timeout(45000)
    try:
        # ---- login (SPA: esperar o conteúdo, não a navegação) ----
        page.goto("https://app.konclui.com/login", wait_until="networkidle")
        page.wait_for_selector("input[type=email]", timeout=45000)
        page.fill("input[type=email]", EMAIL)
        page.fill("input[type=password]", SENHA)
        page.get_by_role("button", name=re.compile("entrar", re.I)).click()
        # dashboard carregado = apareceu "checklists agendados"
        page.wait_for_selector("text=checklists agendados", timeout=60000)
        # ---- mês vigente ----
        page.goto(f"https://app.konclui.com/?dateFrom={primeiro}", wait_until="networkidle")
        page.wait_for_selector("text=Ranking por usuários", timeout=60000)
        page.wait_for_timeout(4000)  # deixa o ranking/KPIs renderizarem
        texto = page.locator("main").inner_text()
        (DEBUG / "pagina.txt").write_text(texto, encoding="utf-8")
        page.screenshot(path=str(DEBUG / "dashboard.png"), full_page=True)
    except Exception as e:
        dump_erro(page, e)
        browser.close()
        print(f"ERRO no login/leitura: {e} (ver debug/erro.png e debug/erro.html)", file=sys.stderr)
        sys.exit(3)
    browser.close()

colabs = [c for c in parse_ranking(texto, "Pontuação consolidada de cada integrante", "Ranking por unidades")
          if c[0].strip().lower() not in EXCLUIR]
setores = parse_ranking(texto, "Resultado operacional de cada setor", "Evolução dos indicadores")
# normaliza nomes de setor para Title Case
setores = [[s[0].title(), s[1]] for s in setores]

total = kpi_apos(texto, "checklists agendados no período")
finalizado = kpi_apos(texto, "Finalizado")
nao_exec = kpi_apos(texto, "Não executado")
atrasado = kpi_apos(texto, "Atrasado")
taxa = pct_do_total(texto, "Finalizado")
nao_exec_pct = pct_do_total(texto, "Não executado")

if not colabs or taxa is None:
    print("ERRO: não consegui ler o ranking/KPIs (ver debug/pagina.txt).", file=sys.stderr)
    sys.exit(2)

dados = {
    "periodo": periodo_label,
    "taxa": taxa, "finalizado": finalizado, "total": total,
    "nao_exec": nao_exec, "nao_exec_pct": nao_exec_pct, "atrasado": atrasado if atrasado is not None else 0,
    "colabs": colabs, "setores": setores,
    "gerado": hoje.strftime("%d/%m/%Y"),
}
(DEBUG / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Desempenho da Equipe — Koncluí</title>
<style>
  :root{--navy:#10233A;--green:#13B981;--greend:#0B7C57;--amber:#E0891F;--gray:#AEB7C2;
    --ink:#1F2A37;--mut:#5B6875;--line:#E2E7EC;--bg:#F4F6F8;--card:#FFFFFF;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--ink);padding:18px}
  .wrap{max-width:1040px;margin:0 auto}
  .banner{background:var(--navy);color:#fff;border-radius:14px;padding:18px 22px;border-bottom:4px solid var(--green)}
  .banner h1{font-size:22px;font-weight:700}
  .banner .sub{color:#BFEBDD;font-size:13px;margin-top:3px}
  .banner .per{color:#9FB4C7;font-size:12px;margin-top:8px;font-weight:600;letter-spacing:.5px}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
  .kpi .lb{font-size:11px;color:var(--mut);font-weight:700;letter-spacing:.6px;text-transform:uppercase}
  .kpi .vl{font-size:26px;font-weight:700;color:var(--navy);margin-top:4px}
  .kpi .vl small{font-size:13px;color:var(--mut);font-weight:600}
  .grid{display:grid;grid-template-columns:1.25fr 1fr;gap:14px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .card h2{font-size:14px;color:var(--navy);font-weight:700;margin-bottom:2px}
  .card .cap{font-size:11px;color:var(--mut);margin-bottom:12px}
  .row{display:flex;align-items:center;gap:8px;margin:7px 0}
  .nm{width:150px;font-size:12.5px;font-weight:600;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .track{position:relative;flex:1;height:18px;background:#EEF2F6;border-radius:6px;overflow:hidden}
  .fill{height:100%;border-radius:6px}
  .meta{position:absolute;top:-3px;bottom:-3px;left:90%;width:0;border-left:2px dashed var(--greend)}
  .pct{width:42px;text-align:right;font-size:12.5px;font-weight:700;color:var(--ink)}
  .setor .nm{width:120px}
  .legend{display:flex;flex-wrap:wrap;gap:14px;margin:14px 2px 2px;font-size:12px;color:var(--mut)}
  .legend span{display:flex;align-items:center;gap:6px}
  .dot{width:12px;height:12px;border-radius:3px;display:inline-block}
  .foot{margin-top:14px;font-size:11px;color:var(--mut);text-align:center}
  @media(max-width:720px){.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.nm{width:130px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="banner">
    <h1>Painel de Desempenho da Equipe</h1>
    <div class="sub">Koncluí · Spazio Gourmet &amp; Kūkan Sushi — % de execução das rotinas (abertura e fechamento)</div>
    <div class="per">__PERIODO__</div>
  </div>
  <div class="kpis">
    <div class="kpi"><div class="lb">Taxa de conclusão</div><div class="vl">__TAXA__%</div></div>
    <div class="kpi"><div class="lb">Finalizados</div><div class="vl">__FIN__ <small>/ __TOT__</small></div></div>
    <div class="kpi"><div class="lb">Não executado</div><div class="vl">__NE__ <small>(__NEP__%)</small></div></div>
    <div class="kpi"><div class="lb">Atrasado</div><div class="vl">__ATR__</div></div>
  </div>
  <div class="grid">
    <div class="card">
      <h2>Desempenho por colaborador</h2>
      <div class="cap">Pontuação consolidada (Score) de cada integrante · tracinho = meta 90%</div>
      <div id="colabs"></div>
    </div>
    <div class="card setor">
      <h2>Desempenho por setor</h2>
      <div class="cap">Resultado operacional de cada setor</div>
      <div id="setores"></div>
    </div>
  </div>
  <div class="legend">
    <span><i class="dot" style="background:#0B7C57"></i> 95%+ Turbinado</span>
    <span><i class="dot" style="background:#13B981"></i> 90–94% Prêmio cheio</span>
    <span><i class="dot" style="background:#E0891F"></i> 80–89% Meio prêmio</span>
    <span><i class="dot" style="background:#AEB7C2"></i> Abaixo de 80% Sem prêmio</span>
  </div>
  <div class="foot">Fonte: Koncluí · atualizado automaticamente na madrugada · última atualização: __GERADO__</div>
</div>
<script>
  var colabs=__COLABS__;
  var setores=__SETORES__;
  function cor(v){ if(v>=95)return'#0B7C57'; if(v>=90)return'#13B981'; if(v>=80)return'#E0891F'; return'#AEB7C2'; }
  function render(id,arr,meta){
    document.getElementById(id).innerHTML=arr.map(function(r){
      return '<div class="row"><div class="nm" title="'+r[0]+'">'+r[0]+'</div>'+
        '<div class="track"><div class="fill" style="width:'+r[1]+'%;background:'+cor(r[1])+'"></div>'+
        (meta?'<div class="meta"></div>':'')+'</div><div class="pct">'+r[1]+'%</div></div>';
    }).join('');
  }
  render('colabs',colabs,true); render('setores',setores,false);
</script>
</body>
</html>"""

html = (TEMPLATE
    .replace("__PERIODO__", dados["periodo"])
    .replace("__TAXA__", str(dados["taxa"]))
    .replace("__FIN__", str(dados["finalizado"] if dados["finalizado"] is not None else "—"))
    .replace("__TOT__", str(dados["total"] if dados["total"] is not None else "—"))
    .replace("__NE__", str(dados["nao_exec"] if dados["nao_exec"] is not None else "—"))
    .replace("__NEP__", str(dados["nao_exec_pct"] if dados["nao_exec_pct"] is not None else "—"))
    .replace("__ATR__", str(dados["atrasado"]))
    .replace("__GERADO__", dados["gerado"])
    .replace("__COLABS__", json.dumps(colabs, ensure_ascii=False))
    .replace("__SETORES__", json.dumps(setores, ensure_ascii=False)))

(SITE / "index.html").write_text(html, encoding="utf-8")
print(f"OK: painel gerado — {len(colabs)} colaboradores, {len(setores)} setores, taxa {taxa}%.")
