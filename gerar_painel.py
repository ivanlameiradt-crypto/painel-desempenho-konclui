# -*- coding: utf-8 -*-
"""
Robo da nuvem (GitHub Actions): faz login no Konclui, le o dashboard do mes vigente
E do mes anterior (para a evolucao), e gera site/index.html
(Painel de Desempenho da Equipe - visual escuro, no estilo do Painel Gerencial da Spazio).
Sem custo, sem o PC do Ivan. Credenciais vem dos secrets KONCLUI_EMAIL e KONCLUI_SENHA.
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
primeiro_date = hoje.replace(day=1)
primeiro = primeiro_date.isoformat()
# mes anterior (mes fechado) = base da evolucao
prev_last = primeiro_date - datetime.timedelta(days=1)
prev_first = prev_last.replace(day=1)
prev_de, prev_ate = prev_first.isoformat(), prev_last.isoformat()

mes_nome = MESES[hoje.month-1]
mes_ano = f"{mes_nome} de {hoje.year}"
mes_ant_nome = MESES[prev_first.month-1]
titulo_sub = f"Execução das rotinas no Koncluí · {mes_ano} · abertura e fechamento"
hero_sub = f"{mes_nome} · mês em andamento, até {hoje.strftime('%d/%m')}"

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

def ler_mes(page, url):
    """Abre a URL de um periodo e devolve o inner_text do main (ou '' se falhar)."""
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("text=Ranking por usuários", timeout=60000)
    page.wait_for_timeout(4000)  # deixa o ranking/KPIs renderizarem
    return page.locator("main").inner_text()

texto = ""
texto_ant = ""
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
        texto = ler_mes(page, f"https://app.konclui.com/?dateFrom={primeiro}")
        (DEBUG / "pagina.txt").write_text(texto, encoding="utf-8")
        page.screenshot(path=str(DEBUG / "dashboard.png"), full_page=True)
    except Exception as e:
        dump_erro(page, e)
        browser.close()
        print(f"ERRO no login/leitura: {e} (ver debug/erro.png e debug/erro.html)", file=sys.stderr)
        sys.exit(3)
    # ---- mês anterior (para a evolução) — nunca derruba o painel ----
    try:
        texto_ant = ler_mes(page, f"https://app.konclui.com/?dateFrom={prev_de}&dateTo={prev_ate}")
        (DEBUG / "pagina_anterior.txt").write_text(texto_ant, encoding="utf-8")
    except Exception as e2:
        texto_ant = ""
        print(f"AVISO: não li o mês anterior ({e2}); painel sai sem setas de evolução.", file=sys.stderr)
    browser.close()

colabs = [c for c in parse_ranking(texto, "Pontuação consolidada de cada integrante", "Ranking por unidades")
          if c[0].strip().lower() not in EXCLUIR]

taxa = pct_do_total(texto, "Finalizado")

if not colabs or taxa is None:
    print("ERRO: não consegui ler o ranking/KPIs (ver debug/pagina.txt).", file=sys.stderr)
    sys.exit(2)

# ---- evolução: mapa do mês anterior {nome: pct} ----
colabs_ant = [c for c in parse_ranking(texto_ant, "Pontuação consolidada de cada integrante", "Ranking por unidades")
              if c[0].strip().lower() not in EXCLUIR] if texto_ant else []
prev_map = {c[0].strip().lower(): c[1] for c in colabs_ant}
tem_anterior = len(prev_map) > 0

def delta_de(nome, pct):
    if not tem_anterior:
        return None
    k = nome.strip().lower()
    return (pct - prev_map[k]) if k in prev_map else "novo"

# cada item: [nome, pct, delta]  (delta = int, "novo", ou null se não há mês anterior)
colabs2 = [[c[0], c[1], delta_de(c[0], c[1])] for c in colabs]

dados = {
    "mes_ano": mes_ano, "mes_anterior": mes_ant_nome, "tem_anterior": tem_anterior,
    "taxa": taxa, "colabs": colabs2, "gerado": hoje.strftime("%d/%m/%Y"),
}
(DEBUG / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Desempenho da Equipe — Koncluí</title>
<style>
  :root{
    --bg:#0f1117;--card:#181b23;--card2:#20242e;--line:#2a2f3a;--tx:#e8eaed;--tx2:#9aa0ac;
    --acc:#3987e5;--good:#3fbf3f;--warn:#eda100;--crit:#e3776a;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--tx);padding:24px}
  .wrap{max-width:1120px;margin:0 auto}
  h1{font-size:22px;font-weight:720;letter-spacing:-.3px}
  .sub{color:var(--tx2);font-size:13px;margin-top:3px}
  h2{font-size:14px;font-weight:650;margin:0 0 4px}
  .h2sub{font-size:12px;color:var(--tx2);margin-bottom:14px}
  .topbar{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding:4px 0 16px;margin-bottom:18px}
  .fref{font-size:11.5px;font-weight:600;color:var(--tx2);background:var(--card2);border:1px solid var(--line);border-radius:100px;padding:5px 13px}
  .live{background:linear-gradient(135deg,#12172a,#181b23);border:1px solid #2a3550;border-radius:16px;padding:20px 22px;margin:0 0 18px}
  .live-h{display:flex;align-items:center;gap:10px;margin-bottom:18px;flex-wrap:wrap}
  .live-dot{width:9px;height:9px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 0 rgba(34,197,94,.5);animation:pulse 1.8s infinite;flex:none}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}70%{box-shadow:0 0 0 9px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
  @media(prefers-reduced-motion:reduce){.live-dot{animation:none}}
  .live-body{display:grid;grid-template-columns:220px 1fr;gap:26px;align-items:center}
  .gwrap{text-align:center}
  .glabel{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--tx2);margin-bottom:6px}
  .gcap{font-size:11.5px;color:var(--tx2);margin-top:8px}
  .gcap b{color:var(--tx);font-variant-numeric:tabular-nums}
  .cells{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
  .cell{background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .cell .l{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--tx2)}
  .cell .v{font-size:26px;font-weight:720;letter-spacing:-.5px;margin-top:4px;font-variant-numeric:tabular-nums}
  .cell .d{font-size:11.5px;color:var(--tx2);margin-top:2px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:18px}
  .rhead,.rrow{display:grid;grid-template-columns:28px minmax(150px,1fr) 230px 56px 112px 70px;gap:16px;align-items:center}
  .rhead{padding:4px 0 12px;border-bottom:1px solid var(--line)}
  .rhead div{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--tx2);font-weight:600}
  .rhead .r{text-align:right}
  .rrow{padding:12px 0;border-bottom:1px solid var(--line)}
  .rrow:last-child{border-bottom:none}
  .rrow.lead{background:rgba(57,135,229,.07);margin:0 -20px;padding-left:20px;padding-right:20px;border-radius:10px}
  .rk{font-size:13px;font-weight:700;color:var(--tx2);text-align:center;font-variant-numeric:tabular-nums}
  .nm{display:flex;align-items:center;gap:10px;min-width:0}
  .cdot{width:9px;height:9px;border-radius:50%;flex:none}
  .nmtx{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bar{height:8px;background:var(--card2);border:1px solid var(--line);border-radius:100px;overflow:hidden}
  .bar>i{display:block;height:100%;border-radius:100px}
  .pc{font-size:20px;font-weight:720;text-align:right;font-variant-numeric:tabular-nums;letter-spacing:-.3px}
  .tag{justify-self:start;display:inline-block;border-radius:100px;font-size:10.5px;font-weight:700;padding:3px 11px;white-space:nowrap}
  .tOk{color:#3fbf3f;background:rgba(63,191,63,.14)}
  .tWarn{color:#eda100;background:rgba(237,161,0,.14)}
  .tOff{color:#9aa0ac;background:rgba(136,146,160,.16)}
  .evo{font-size:13.5px;font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
  .evo .ar{font-size:10px;margin-right:2px}
  .novo{color:var(--tx2);font-weight:600;font-size:12px}
  .foot{color:var(--tx2);font-size:12px;text-align:center;margin-top:8px;padding-top:16px;border-top:1px solid var(--line)}
  @media(max-width:860px){
    body{padding:16px}
    .live-body{grid-template-columns:1fr;gap:16px}
    .cells{grid-template-columns:repeat(2,1fr)}
    .rhead,.rrow{grid-template-columns:24px minmax(110px,1fr) 46px 92px;gap:10px}
    .rhead .hbar,.rrow .bar,.rhead .hevo,.rrow .evo{display:none}
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div>
      <h1>Painel de Desempenho · EQUIPE SPAZIO</h1>
      <div class="sub">__TITULOSUB__</div>
    </div>
    <span class="fref">meta 90%</span>
  </div>

  <div class="live">
    <div class="live-h">
      <span class="live-dot"></span>
      <b>Desempenho do mês</b>
      <span class="sub" style="margin:0">__HEROSUB__</span>
    </div>
    <div class="live-body">
      <div class="gwrap">
        <div class="glabel">Média da equipe</div>
        <div id="gauge"></div>
        <div class="gcap">marca branca = <b>meta 90%</b></div>
      </div>
      <div class="cells" id="cells"></div>
    </div>
  </div>

  <div class="card">
    <h2>Ranking da equipe</h2>
    <div class="h2sub">cada colaborador pela sua % de execução · a seta compara com __MESANT__</div>
    <div class="rhead"><div>#</div><div>Colaborador</div><div class="hbar">Execução</div><div class="r">%</div><div>Faixa</div><div class="r hevo">vs. ant.</div></div>
    <div id="rows"></div>
  </div>

  <div class="foot">Atualizado automaticamente na madrugada · fonte: Koncluí · última atualização: __GERADO__ · valores de prêmio ficam na planilha (confidencial)</div>
</div>

<script>
  var COLABS=__COLABS__;      // [nome, pct, delta | "novo" | null]
  var TAXA=__TAXA__;          // taxa de conclusão (%)
  var TEM_ANT=__TEMANT__;     // há mês anterior para comparar?
  function cor(v){return v>=95?'#17b890':v>=90?'#22b36b':v>=80?'#eda100':'#737d8c';}
  function fx(v){return v>=95?['Turbinado','tOk']:v>=90?['Na meta','tOk']:v>=80?['Meio prêmio','tWarn']:['Abaixo','tOff'];}

  (function(){
    var cx=100,cy=100,r=78,st=15,C=2*Math.PI*r,track=C*0.75;
    var media=COLABS.length?Math.round(COLABS.reduce(function(a,d){return a+d[1];},0)/COLABS.length):0;
    var val=track*(media/100);
    function pt(frac){var ang=(135+frac*270)*Math.PI/180;return [cx+r*Math.cos(ang),cy+r*Math.sin(ang)];}
    var mt=pt(0.90);
    document.getElementById('gauge').innerHTML=
      '<svg viewBox="0 0 200 200" width="200" height="200">'+
      '<g transform="rotate(135 '+cx+' '+cy+')">'+
      '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="#2a2f3a" stroke-width="'+st+'" stroke-linecap="round" stroke-dasharray="'+track+' '+C+'"/>'+
      '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="#3987e5" stroke-width="'+st+'" stroke-linecap="round" stroke-dasharray="'+val+' '+C+'"/>'+
      '</g>'+
      '<circle cx="'+mt[0].toFixed(1)+'" cy="'+mt[1].toFixed(1)+'" r="4.5" fill="#e8eaed"/>'+
      '<text x="'+cx+'" y="'+(cy-2)+'" text-anchor="middle" fill="#e8eaed" font-size="42" font-weight="720" font-family="system-ui" style="font-variant-numeric:tabular-nums">'+media+'<tspan font-size="20">%</tspan></text>'+
      '<text x="'+cx+'" y="'+(cy+22)+'" text-anchor="middle" fill="#9aa0ac" font-size="12">execução</text>'+
      '</svg>';

    var na=COLABS.filter(function(d){return d[1]>=90;}).length;
    var meio=COLABS.filter(function(d){return d[1]>=80&&d[1]<90;}).length;
    var ab=COLABS.filter(function(d){return d[1]<80;}).length;
    function cell(l,v,d,c){return '<div class="cell"><div class="l">'+l+'</div><div class="v" style="color:'+c+'">'+v+'</div><div class="d">'+d+'</div></div>';}
    document.getElementById('cells').innerHTML=
      cell('Na meta (90%+)',na,'prêmio cheio','#3fbf3f')+
      cell('Meio prêmio (80–89%)',meio,'a caminho','#eda100')+
      cell('Abaixo de 80%',ab,'sem prêmio ainda','#9aa0ac')+
      cell('Taxa de conclusão',TAXA+'%','checklists finalizados','#e8eaed');
  })();

  function evo(d){
    if(!TEM_ANT) return '<span style="color:var(--tx2)">—</span>';
    if(d==="novo"||d===null) return '<span class="novo">novo</span>';
    if(d>0) return '<span style="color:var(--good)"><span class="ar">▲</span>'+d+'</span>';
    if(d<0) return '<span style="color:var(--crit)"><span class="ar">▼</span>'+Math.abs(d)+'</span>';
    return '<span style="color:var(--tx2)">—</span>';
  }
  document.getElementById('rows').innerHTML=COLABS.map(function(d,i){
    var v=d[1],c=cor(v),f=fx(v);
    return '<div class="rrow'+(i===0?' lead':'')+'">'+
      '<div class="rk">'+(i+1)+'</div>'+
      '<div class="nm"><span class="cdot" style="background:'+c+'"></span><span class="nmtx" title="'+d[0]+'">'+d[0]+'</span></div>'+
      '<div class="bar"><i style="width:'+v+'%;background:'+c+'"></i></div>'+
      '<div class="pc">'+v+'</div>'+
      '<span class="tag '+f[1]+'">'+f[0]+'</span>'+
      '<div class="evo">'+evo(d[2])+'</div></div>';
  }).join('');
</script>
</body>
</html>"""

html = (TEMPLATE
    .replace("__TITULOSUB__", titulo_sub)
    .replace("__HEROSUB__", hero_sub)
    .replace("__MESANT__", mes_ant_nome)
    .replace("__TAXA__", str(taxa))
    .replace("__TEMANT__", "true" if tem_anterior else "false")
    .replace("__GERADO__", dados["gerado"])
    .replace("__COLABS__", json.dumps(colabs2, ensure_ascii=False)))

(SITE / "index.html").write_text(html, encoding="utf-8")
print(f"OK: painel gerado — {len(colabs2)} colaboradores, taxa {taxa}%, "
      f"evolução {'ON ('+mes_ant_nome+')' if tem_anterior else 'OFF'}.")
