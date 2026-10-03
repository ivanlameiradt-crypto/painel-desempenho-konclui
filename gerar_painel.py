# -*- coding: utf-8 -*-
"""
Robo da nuvem (GitHub Actions): faz login no Konclui, le a VISAO GERAL do dashboard
do mes vigente (e o mes anterior, para a evolucao por usuario) e gera site/index.html
replicando a visao geral do Konclui no visual escuro do Painel Gerencial da Spazio:
 - 5 cartoes de status (com tendencia, % do total e sparkline do historico)
 - Taxa de conclusao (medidor meia-lua)
 - 3 rankings: usuarios (com evolucao vs mes anterior), unidades, setores
 - Grafico "Evolucao dos indicadores" (Score medio + Taxa por dia), que enche com o
   historico diario guardado em site/historico.json (lido da propria URL do Pages).
Sem custo, sem o PC do Ivan. Credenciais vem dos secrets KONCLUI_EMAIL e KONCLUI_SENHA.
Funcoes puras (parsers + build_html) ficam no topo para serem testadas sem login.
"""
import os, re, sys, json, datetime, pathlib, traceback, urllib.request

BASE = pathlib.Path(__file__).parent
SITE = BASE / "site"
DEBUG = BASE / "debug"
PAGES_URL = "https://ivanlameiradt-crypto.github.io/painel-desempenho-konclui"

MESES = ["janeiro","fevereiro","março","abril","maio","junho","julho","agosto",
         "setembro","outubro","novembro","dezembro"]

EXCLUIR = {"usuário geral", "usuario geral"}
STATUS_ORDER = ["Não iniciado", "Iniciado", "Atrasado", "Não executado", "Finalizado"]
SHORT = {"Não iniciado":"ni","Iniciado":"ini","Atrasado":"atr","Não executado":"nex","Finalizado":"fin"}

# ---------------- parsers (puros) ----------------
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
            if re.fullmatch(r"\d{1,3}", nome):
                continue
            if len(nome) <= 3 and nome.isupper():
                continue
            out.append([nome, int(m.group(1))])
    return out

def parse_status(texto):
    i = texto.find("checklists agendados no período")
    j = texto.find("Taxa de conclusão")
    seg = texto[i:j] if (i != -1 and j != -1) else texto
    linhas = [l.strip() for l in seg.splitlines() if l.strip()]
    out = {}
    for idx, l in enumerate(linhas):
        if l in STATUS_ORDER and l not in out:
            resto = linhas[idx+1:idx+4]
            count = trend = pct = None
            if len(resto) >= 1 and re.fullmatch(r"-?\d[\d.]*", resto[0]):
                count = int(resto[0].replace(".", ""))
            if len(resto) >= 2:
                trend = resto[1]
            if len(resto) >= 3:
                mm = re.search(r"(\d{1,3})%\s*do total", resto[2])
                pct = int(mm.group(1)) if mm else None
            out[l] = {"count": count, "trend": trend, "pct": pct}
    return out

def total_checklists(texto):
    m = re.search(r"(\d[\d.]*)\s*checklists agendados no período", texto)
    return int(m.group(1).replace(".", "")) if m else None

def pct_do_total(texto, label):
    i = texto.find(label)
    if i == -1: return None
    m = re.search(r"(\d{1,3})%\s*do total", texto[i+len(label):])
    return int(m.group(1)) if m else None

# ---------------- montagem dos dados ----------------
def montar_dados(texto, texto_ant, agora):
    # agora pode ser datetime (produção, com hora) ou date (testes, só data)
    if isinstance(agora, datetime.datetime):
        hoje = agora.date()
        gerado = agora.strftime("%d/%m/%Y às %H:%M") + " (Brasília)"
    else:
        hoje = agora
        gerado = hoje.strftime("%d/%m/%Y")
    usuarios = [c for c in parse_ranking(texto, "Pontuação consolidada de cada integrante", "Ranking por unidades")
                if c[0].strip().lower() not in EXCLUIR]
    unidades = parse_ranking(texto, "Desempenho entre as unidades", "Ranking por setores")
    setores  = parse_ranking(texto, "Resultado operacional de cada setor", "Evolução dos indicadores")

    taxa = pct_do_total(texto, "Finalizado")
    status = parse_status(texto)
    total = total_checklists(texto)
    status_list = [[lab, status[lab]["count"], status[lab]["trend"], status[lab]["pct"]]
                   for lab in STATUS_ORDER if lab in status]

    usuarios_ant = [c for c in parse_ranking(texto_ant, "Pontuação consolidada de cada integrante", "Ranking por unidades")
                    if c[0].strip().lower() not in EXCLUIR] if texto_ant else []
    prev_map = {c[0].strip().lower(): c[1] for c in usuarios_ant}
    tem_anterior = len(prev_map) > 0

    def delta_de(nome, pct):
        if not tem_anterior:
            return None
        k = nome.strip().lower()
        return (pct - prev_map[k]) if k in prev_map else "novo"

    usuarios2 = [[c[0], c[1], delta_de(c[0], c[1])] for c in usuarios]
    score = round(sum(c[1] for c in usuarios) / len(usuarios)) if usuarios else 0

    snap = {"data": hoje.isoformat(), "taxa": taxa, "score": score}
    for lab in STATUS_ORDER:
        s = status.get(lab, {})
        k = SHORT[lab]
        snap[k] = s.get("count")
        snap[k + "_p"] = s.get("pct")

    prev_first = hoje.replace(day=1) - datetime.timedelta(days=1)
    return {
        "mes_nome": MESES[hoje.month-1], "ano": hoje.year,
        "mes_anterior": MESES[prev_first.month-1], "tem_anterior": tem_anterior,
        "ate": hoje.strftime("%d/%m"), "gerado": gerado,
        "total": total, "taxa": taxa, "score": score, "status": status_list,
        "usuarios": usuarios2, "unidades": unidades, "setores": setores, "snap": snap,
    }

# ---------------- template + build_html (puros) ----------------
TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Desempenho da Equipe — Koncluí</title>
<style>
  :root{
    --bg:#0f1117;--card:#181b23;--card2:#20242e;--line:#2a2f3a;--tx:#e8eaed;--tx2:#9aa0ac;
    --acc:#3987e5;--good:#3fbf3f;--warn:#eda100;--crit:#e3776a;--slate:#737d8c;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--tx);padding:24px}
  .wrap{max-width:1200px;margin:0 auto}
  h1{font-size:22px;font-weight:720;letter-spacing:-.3px}
  .sub{color:var(--tx2);font-size:13px;margin-top:3px}
  .topbar{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding:4px 0 16px;margin-bottom:18px}
  .fref{font-size:11.5px;font-weight:600;color:var(--tx2);background:var(--card2);border:1px solid var(--line);border-radius:100px;padding:5px 13px}

  .kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:18px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px}
  .kpi .top{display:flex;align-items:center;gap:8px}
  .kpi .ic{width:11px;height:11px;border-radius:50%;flex:none;border:2px solid currentColor}
  .kpi .lb{font-size:12.5px;color:var(--tx);font-weight:600}
  .kpi .n{font-size:29px;font-weight:720;letter-spacing:-.5px;margin-top:7px;font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:9px}
  .kpi .tr{font-size:12px;font-weight:700}
  .kpi .pt{font-size:11.5px;color:var(--tx2);margin-top:3px}
  .kpi .spark{display:block;width:100%;height:26px;margin-top:6px;opacity:.9}

  .ov{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:18px}
  .ov .card{margin-bottom:0}
  .card h2{font-size:14px;font-weight:650;margin:0 0 2px}
  .card .cap{font-size:11.5px;color:var(--tx2);margin-bottom:12px;min-height:16px}
  .donutwrap{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:10px 0}
  .donutcap{font-size:12px;color:var(--tx2);margin-top:2px}
  .rk-list{max-height:342px;overflow:auto}
  .rk-item{display:grid;grid-template-columns:20px 1fr auto;gap:9px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
  .rk-item:last-child{border-bottom:none}
  .rk-pos{font-size:12px;color:var(--tx2);font-weight:700;text-align:center;font-variant-numeric:tabular-nums}
  .rk-nm{display:flex;align-items:center;gap:8px;min-width:0}
  .rk-dot{width:8px;height:8px;border-radius:50%;flex:none}
  .rk-nmtx{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .rk-right{display:flex;align-items:center;gap:7px;white-space:nowrap}
  .rk-pc{font-size:14px;font-weight:720;font-variant-numeric:tabular-nums}
  .rk-evo{font-size:10.5px;font-weight:700;font-variant-numeric:tabular-nums}
  .rk-evo .ar{font-size:9px}
  .novo{color:var(--tx2);font-weight:600;font-size:10px}

  .evo-legend{display:flex;gap:16px;margin:2px 0 10px;font-size:12px;color:var(--tx2)}
  .evo-legend span{display:inline-flex;align-items:center;gap:7px}
  .evo-legend i{width:14px;height:3px;border-radius:2px;display:inline-block}
  .evo-empty{color:var(--tx2);font-size:13px;background:var(--card2);border:1px dashed var(--line);border-radius:10px;padding:22px 18px;text-align:center}
  #evochart svg{display:block;width:100%;height:auto}

  .foot{color:var(--tx2);font-size:12px;text-align:center;margin-top:18px;padding-top:16px;border-top:1px solid var(--line)}
  .rk-list::-webkit-scrollbar{width:8px}.rk-list::-webkit-scrollbar-thumb{background:var(--line);border-radius:8px}
  @media(max-width:980px){.kpis{grid-template-columns:repeat(2,1fr)}.ov{grid-template-columns:1fr}.rk-list{max-height:none}}
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

  <div class="kpis" id="kpis"></div>

  <div class="ov" style="margin-bottom:18px">
    <div class="card">
      <h2>Taxa de conclusão</h2>
      <div class="cap">percentual de finalização no período</div>
      <div class="donutwrap"><div id="donut"></div><div class="donutcap">finalizados</div></div>
    </div>
    <div class="card">
      <h2>Ranking por usuários</h2>
      <div class="cap">pontuação consolidada de cada integrante__EVOCAP__</div>
      <div class="rk-list" id="usuarios"></div>
    </div>
    <div class="card">
      <h2>Ranking por unidades</h2>
      <div class="cap">desempenho entre as unidades</div>
      <div class="rk-list" id="unidades"></div>
    </div>
    <div class="card">
      <h2>Ranking por setores</h2>
      <div class="cap">resultado operacional de cada setor</div>
      <div class="rk-list" id="setores"></div>
    </div>
  </div>

  <div class="card">
    <h2>Evolução dos indicadores</h2>
    <div class="cap">score médio da equipe e taxa de conclusão por dia · o histórico enche a cada atualização</div>
    <div class="evo-legend"><span><i style="background:#3987e5"></i>Score médio</span><span><i style="background:#22b36b"></i>Taxa de conclusão</span></div>
    <div id="evochart"></div>
  </div>

  <div class="foot">Atualizado automaticamente na madrugada · fonte: Koncluí · última atualização: __GERADO__ · valores de prêmio ficam na planilha (confidencial)</div>
</div>

<script>
  var STATUS=__STATUS__;
  var USUARIOS=__USUARIOS__;
  var UNIDADES=__UNIDADES__;
  var SETORES=__SETORES__;
  var TAXA=__TAXA__;
  var TEM_ANT=__TEMANT__;
  var HIST=__HISTORICO__;   // [{data,taxa,score, ni,ni_p, ini,ini_p, atr,atr_p, nex,nex_p, fin,fin_p}]

  function cor(v){return v>=95?'#17b890':v>=90?'#22b36b':v>=80?'#eda100':'#737d8c';}
  var ICON={'Não iniciado':'#3987e5','Iniciado':'#eda100','Atrasado':'#e3776a','Não executado':'#e3776a','Finalizado':'#3fbf3f'};
  var SHORTJS={'Não iniciado':'ni','Iniciado':'ini','Atrasado':'atr','Não executado':'nex','Finalizado':'fin'};
  var BOM_SOBE={'Finalizado':1,'Iniciado':1};

  function spark(vals,color){
    vals=vals.filter(function(v){return v!=null;});
    if(vals.length<2) return '';
    var w=100,h=26,mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals),rng=(mx-mn)||1;
    var pts=vals.map(function(v,i){var x=i/(vals.length-1)*w;var y=h-2-((v-mn)/rng)*(h-4);return x.toFixed(1)+','+y.toFixed(1);}).join(' ');
    return '<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>';
  }
  function trendHTML(label,t){
    if(t==null) return '';
    t=(''+t).trim();
    if(t===''||t==='—'||t==='-') return '<span class="tr" style="color:var(--tx2)">—</span>';
    var sobe=t[0]==='+', desce=(t[0]==='−'||t[0]==='-');
    var ar = sobe?'▲':(desce?'▼':'');
    var bom = (sobe&&BOM_SOBE[label])||(desce&&!BOM_SOBE[label]);
    var c = (sobe||desce)?(bom?'var(--good)':'var(--crit)'):'var(--tx2)';
    return '<span class="tr" style="color:'+c+'">'+ar+' '+t+'</span>';
  }
  document.getElementById('kpis').innerHTML=STATUS.map(function(s){
    var label=s[0],count=s[1],trend=s[2],pct=s[3],c=ICON[label]||'#9aa0ac',key=SHORTJS[label];
    var serie=HIST.map(function(h){return h[key+'_p'];});
    return '<div class="kpi">'+
      '<div class="top"><span class="ic" style="color:'+c+'"></span><span class="lb">'+label+'</span></div>'+
      '<div class="n">'+(count==null?'—':count)+trendHTML(label,trend)+'</div>'+
      '<div class="pt">'+(pct==null?'':pct+'% do total')+'</div>'+
      spark(serie,c)+'</div>';
  }).join('');

  // donut meia-lua (270°) da taxa
  (function(){
    var cx=85,cy=92,r=66,st=16,C=2*Math.PI*r,track=C*0.75,val=track*((TAXA||0)/100);
    document.getElementById('donut').innerHTML=
      '<svg viewBox="0 0 170 150" width="190">'+
      '<g transform="rotate(135 '+cx+' '+cy+')">'+
      '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="#2a2f3a" stroke-width="'+st+'" stroke-linecap="round" stroke-dasharray="'+track+' '+C+'"/>'+
      '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="#22b36b" stroke-width="'+st+'" stroke-linecap="round" stroke-dasharray="'+val+' '+C+'"/>'+
      '</g>'+
      '<text x="'+cx+'" y="'+(cy-2)+'" text-anchor="middle" fill="#e8eaed" font-size="34" font-weight="720" font-family="system-ui" style="font-variant-numeric:tabular-nums">'+(TAXA==null?'—':TAXA+'%')+'</text>'+
      '<text x="'+cx+'" y="'+(cy+20)+'" text-anchor="middle" fill="#9aa0ac" font-size="12">conclusão</text>'+
      '</svg>';
  })();

  function evoHTML(d){
    if(!TEM_ANT) return '';
    if(d==="novo"||d===null) return '<span class="novo">novo</span>';
    if(d>0) return '<span class="rk-evo" style="color:var(--good)"><span class="ar">▲</span>'+d+'</span>';
    if(d<0) return '<span class="rk-evo" style="color:var(--crit)"><span class="ar">▼</span>'+Math.abs(d)+'</span>';
    return '<span class="rk-evo" style="color:var(--tx2)">—</span>';
  }
  function listaRk(id,arr,comEvo){
    document.getElementById(id).innerHTML=arr.map(function(d,i){
      var v=d[1],c=cor(v);
      return '<div class="rk-item"><div class="rk-pos">'+(i+1)+'</div>'+
        '<div class="rk-nm"><span class="rk-dot" style="background:'+c+'"></span><span class="rk-nmtx" title="'+d[0]+'">'+d[0]+'</span></div>'+
        '<div class="rk-right"><span class="rk-pc" style="color:'+c+'">'+v+'%</span>'+(comEvo?evoHTML(d[2]):'')+'</div></div>';
    }).join('');
  }
  listaRk('usuarios',USUARIOS,true);
  listaRk('unidades',UNIDADES,false);
  listaRk('setores',SETORES,false);

  // gráfico de evolução (Score médio + Taxa por dia)
  (function(){
    var el=document.getElementById('evochart');
    if(!HIST || HIST.length<2){
      el.innerHTML='<div class="evo-empty">O histórico começa a ser registrado agora. O gráfico aparece a partir da próxima atualização e vai mostrando a evolução da equipe, dia a dia.</div>';
      return;
    }
    var W=1000,H=250,pL=30,pR=14,pT=12,pB=28,n=HIST.length;
    function X(i){return pL+i/(n-1)*(W-pL-pR);}
    function Y(v){return pT+(100-v)/100*(H-pT-pB);}
    var g='';[0,25,50,75,100].forEach(function(q){var y=Y(q);
      g+='<line x1="'+pL+'" y1="'+y+'" x2="'+(W-pR)+'" y2="'+y+'" stroke="#2a2f3a" stroke-width="1"/>'+
         '<text x="'+(pL-6)+'" y="'+(y+4)+'" text-anchor="end" fill="#6b7482" font-size="12">'+q+'</text>';});
    function linha(key,color){var d=HIST.map(function(h,i){return (i?'L':'M')+X(i).toFixed(1)+' '+Y(h[key]||0).toFixed(1);}).join(' ');
      return '<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>';}
    function pontos(key,color){return HIST.map(function(h,i){return '<circle cx="'+X(i).toFixed(1)+'" cy="'+Y(h[key]||0).toFixed(1)+'" r="3" fill="'+color+'"/>';}).join('');}
    function dlab(s){var p=s.split('-');return p[2]+'/'+p[1];}
    var idxs=n<=6?HIST.map(function(_,i){return i;}):[0,Math.floor((n-1)/3),Math.floor(2*(n-1)/3),n-1];
    var xl=idxs.map(function(i){return '<text x="'+X(i).toFixed(1)+'" y="'+(H-7)+'" text-anchor="middle" fill="#6b7482" font-size="12">'+dlab(HIST[i].data)+'</text>';}).join('');
    el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'">'+g+
      linha('score','#3987e5')+linha('taxa','#22b36b')+
      pontos('score','#3987e5')+pontos('taxa','#22b36b')+xl+'</svg>';
  })();
</script>
</body>
</html>"""

def build_html(d, historico):
    titulo_sub = (f"Este mês · {d['mes_nome']} de {d['ano']} (até {d['ate']})"
                  f"{(' · ' + str(d['total']) + ' checklists') if d.get('total') is not None else ''}"
                  f" · abertura e fechamento")
    evocap = f" · seta = evolução vs {d['mes_anterior']}" if d["tem_anterior"] else ""
    return (TEMPLATE
        .replace("__TITULOSUB__", titulo_sub)
        .replace("__EVOCAP__", evocap)
        .replace("__GERADO__", d["gerado"])
        .replace("__TAXA__", "null" if d["taxa"] is None else str(d["taxa"]))
        .replace("__TEMANT__", "true" if d["tem_anterior"] else "false")
        .replace("__STATUS__", json.dumps(d["status"], ensure_ascii=False))
        .replace("__USUARIOS__", json.dumps(d["usuarios"], ensure_ascii=False))
        .replace("__UNIDADES__", json.dumps(d["unidades"], ensure_ascii=False))
        .replace("__SETORES__", json.dumps(d["setores"], ensure_ascii=False))
        .replace("__HISTORICO__", json.dumps(historico, ensure_ascii=False)))

# ---------------- histórico (persistido no próprio site publicado) ----------------
def carregar_historico(url):
    try:
        req = urllib.request.Request(url + "/historico.json?t=" + str(int(datetime.datetime.now().timestamp())),
                                     headers={"User-Agent": "painel-bot"})
        with urllib.request.urlopen(req, timeout=20) as r:
            dados = json.loads(r.read().decode("utf-8"))
            return dados if isinstance(dados, list) else []
    except Exception as e:
        print(f"AVISO: histórico ainda não existe/não carregou ({e}); começando um novo.", file=sys.stderr)
        return []

def atualizar_historico(url, snap):
    hist = [h for h in carregar_historico(url) if h.get("data") != snap["data"]]
    hist.append(snap)
    hist.sort(key=lambda h: h.get("data", ""))
    return hist[-60:]

# ---------------- acesso ao Konclui (só em execução real) ----------------
def ler_mes(page, url):
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("text=Ranking por usuários", timeout=60000)
    page.wait_for_timeout(4000)
    return page.locator("main").inner_text()

def dump_erro(page, e):
    try:
        page.screenshot(path=str(DEBUG / "erro.png"), full_page=True)
        (DEBUG / "erro.html").write_text(page.content(), encoding="utf-8")
        (DEBUG / "erro.txt").write_text(f"{e}\nURL: {page.url}\n\n{traceback.format_exc()}", encoding="utf-8")
    except Exception:
        pass

def main():
    from playwright.sync_api import sync_playwright
    EMAIL = os.environ.get("KONCLUI_EMAIL")
    SENHA = os.environ.get("KONCLUI_SENHA")
    if not EMAIL or not SENHA:
        print("ERRO: faltam os secrets KONCLUI_EMAIL / KONCLUI_SENHA.", file=sys.stderr)
        sys.exit(1)
    SITE.mkdir(exist_ok=True); DEBUG.mkdir(exist_ok=True)

    BRT = datetime.timezone(datetime.timedelta(hours=-3))
    agora = datetime.datetime.now(BRT)
    hoje = agora.date()
    primeiro = hoje.replace(day=1)
    prev_last = primeiro - datetime.timedelta(days=1)
    prev_first = prev_last.replace(day=1)

    texto = texto_ant = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(45000)
        try:
            page.goto("https://app.konclui.com/login", wait_until="networkidle")
            page.wait_for_selector("input[type=email]", timeout=45000)
            page.fill("input[type=email]", EMAIL)
            page.fill("input[type=password]", SENHA)
            page.get_by_role("button", name=re.compile("entrar", re.I)).click()
            page.wait_for_selector("text=checklists agendados", timeout=60000)
            texto = ler_mes(page, f"https://app.konclui.com/?dateFrom={primeiro.isoformat()}")
            (DEBUG / "pagina.txt").write_text(texto, encoding="utf-8")
            page.screenshot(path=str(DEBUG / "dashboard.png"), full_page=True)
        except Exception as e:
            dump_erro(page, e); browser.close()
            print(f"ERRO no login/leitura: {e} (ver debug/erro.png)", file=sys.stderr)
            sys.exit(3)
        try:
            texto_ant = ler_mes(page, f"https://app.konclui.com/?dateFrom={prev_first.isoformat()}&dateTo={prev_last.isoformat()}")
            (DEBUG / "pagina_anterior.txt").write_text(texto_ant, encoding="utf-8")
        except Exception as e2:
            texto_ant = ""
            print(f"AVISO: não li o mês anterior ({e2}); painel sai sem setas.", file=sys.stderr)
        browser.close()

    dados = montar_dados(texto, texto_ant, agora)
    if not dados["usuarios"] or dados["taxa"] is None:
        print("ERRO: não consegui ler o ranking/KPIs (ver debug/pagina.txt).", file=sys.stderr)
        sys.exit(2)

    historico = atualizar_historico(PAGES_URL, dados["snap"])
    (SITE / "historico.json").write_text(json.dumps(historico, ensure_ascii=False), encoding="utf-8")
    (DEBUG / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    (SITE / "index.html").write_text(build_html(dados, historico), encoding="utf-8")
    print(f"OK: visão geral gerada — {len(dados['usuarios'])} usuários, "
          f"{len(dados['unidades'])} unidades, {len(dados['setores'])} setores, "
          f"taxa {dados['taxa']}%, score {dados['score']}, histórico {len(historico)} dia(s), "
          f"evolução {'ON' if dados['tem_anterior'] else 'OFF'}.")

if __name__ == "__main__":
    main()
