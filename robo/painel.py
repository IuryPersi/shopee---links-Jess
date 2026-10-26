"""Painel local para testar o robo na pratica: http://127.0.0.1:8031

So escuta em 127.0.0.1 (nao aparece na rede). Botoes rodam os mesmos comandos do terminal
(demo, diagnostico, rodar) num processo separado, um de cada vez, e mostram a saida.
Credenciais NAO passam por aqui: ficam no arquivo .env, editado a mao.

Uso:  py -3.12 -m robo.painel   (ou dois cliques em PAINEL.bat)
"""
from __future__ import annotations

import html
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import RAIZ, ler_env, ler_nicho
from .postagem import MAX_POSTAGENS, VERSAO_POSTAGEM
from .links import (ESTADOS_EXAME, ICONES, MAX_LINKS_COLADOS, VERSAO_CONFERENCIA, endereco_seguro, links_do_texto,
                    nivel_do_exame, texto_do_exame)
from .texto import milhar, reais

PORTA = 8031
SAIDA = RAIZ / "saida"
COMANDOS = {
    "demo": ("Gerar demonstração", ["demo"]),
    "diagnostico": ("Testar conexão com a Shopee", ["diagnostico"]),
    "rodar": ("Atualizar com a conta Shopee", ["rodar"]),
    "resumo": ("Tamanho do histórico", ["resumo"]),
}

_estado = {"rodando": None, "inicio": None, "saida": "", "codigo": None, "ultimo": None,
           "qtd_links": 0, "aviso_conferir": "", "aviso_postagem": ""}
_trava = threading.Lock()
LIMITE_CORPO = 64_000  # bytes do formulario do "Conferir links" (o campo aceita ate 12.000 caracteres)
PRAZO_CORPO = 10.0  # segundos para o formulario chegar INTEIRO (40a rodada: envio lento prendia a linha)


def reservar(nome: str) -> bool:
    """Reserva ATOMICA: verifica e marca como rodando sob a mesma trava (29a rodada do
    Codex: dois POSTs simultaneos podiam iniciar dois processos)."""
    with _trava:
        if _estado["rodando"] is not None:
            return False
        _estado.update(rodando=nome, inicio=time.time(), saida="", codigo=None)
        return True


def _executar(nome: str, args: list[str] | None = None):
    """Roda `python -m robo <args>` (lista, sem shell) e guarda a saida para a tela."""
    if args is None:
        _, args = COMANDOS[nome]
    try:
        proc = subprocess.Popen([sys.executable, "-m", "robo", *args], cwd=str(RAIZ),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        for linha in iter(proc.stdout.readline, b""):
            with _trava:
                _estado["saida"] += linha.decode("utf-8", "replace")
        codigo = proc.wait()
    except Exception as e:  # noqa: BLE001 - mostrar no painel, nunca derrubar o servidor
        codigo = -1
        with _trava:
            _estado["saida"] += f"\nfalhou ao iniciar: {e}"
    with _trava:
        _estado.update(rodando=None, codigo=codigo, ultimo=nome)


CSS = """
:root{--fundo:#0e0b0c;--papel:#1a1416;--papel2:#221a1d;--linha:#33282c;--texto:#fbf4ee;--fraco:#b3a39d;
--brasa:#ff4d2e;--brasa2:#ff7a45;--ok:#3ddc84;--aviso:#f5c451}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--fundo);color:var(--texto);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.topo{position:sticky;top:0;z-index:5;background:linear-gradient(180deg,#0e0b0c 70%,#0e0b0ccc);backdrop-filter:blur(6px);
border-bottom:1px solid var(--linha)}
.topo .in{max-width:1180px;margin:0 auto;padding:16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:clamp(26px,5vw,40px);line-height:1;margin:0;letter-spacing:-.03em;font-weight:900}
h1 em{color:var(--brasa);font-style:normal}
.quando{color:var(--fraco);font-size:13px;margin-top:4px}
.esp{flex:1}
form{display:inline;margin:0}
.atualizar{background:var(--brasa);color:#1a0703;border:0;border-radius:999px;padding:12px 20px;font:inherit;font-weight:900;
cursor:pointer;box-shadow:0 6px 24px #ff4d2e40}
.atualizar:disabled{opacity:.55;cursor:wait}
.chips{max-width:1180px;margin:0 auto;padding:12px 16px 0;display:flex;gap:8px;overflow-x:auto}
.chips button{flex:none;background:var(--papel);color:var(--texto);border:1px solid var(--linha);border-radius:999px;padding:8px 14px;
font:inherit;font-size:14px;cursor:pointer}
.chips button.ativo{background:var(--texto);color:#140c0e;border-color:var(--texto);font-weight:800}
main{max-width:1180px;margin:0 auto;padding:8px 16px 60px}
h2{font-size:15px;color:var(--fraco);text-transform:uppercase;letter-spacing:.08em;margin:22px 0 12px;font-weight:700}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}
.card{background:var(--papel);border:1px solid var(--linha);border-radius:18px;overflow:hidden;display:flex;flex-direction:column}
.card[hidden]{display:none}
.foto{position:relative;aspect-ratio:1;background:var(--papel2)}
.foto img{width:100%;height:100%;object-fit:cover;display:block}
.semfoto{display:grid;place-items:center;height:100%;color:var(--fraco);font-size:40px}
.pct{position:absolute;top:10px;left:10px;background:var(--brasa);color:#1a0703;font-weight:900;font-size:20px;padding:4px 10px;border-radius:10px}
.selo{position:absolute;top:10px;right:10px;background:#000b;color:var(--ok);font-weight:800;font-size:11px;padding:4px 8px;border-radius:8px;letter-spacing:.04em}
.corpo{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}
.nome{font-weight:700;font-size:15px;line-height:1.3;margin:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.de{color:var(--fraco);font-size:14px;margin:2px 0 0}
.de s{text-decoration:line-through}
.apartir{display:block;font-size:12px;font-weight:600;color:var(--fraco);letter-spacing:0}
.aviso-card{margin:0;color:var(--aviso);font-size:12px;line-height:1.35}
.conferido{margin:0;color:var(--ok);font-size:12px}
.por{font-size:26px;font-weight:900;margin:0;letter-spacing:-.02em}
.prova{color:var(--fraco);font-size:13px;margin:0}
.copiar{margin-top:auto;background:var(--brasa);color:#1a0703;border:0;border-radius:12px;padding:12px;font:inherit;font-weight:900;cursor:pointer}
.copiar.feito{background:var(--ok);color:#04150b}
.mini{display:flex;gap:6px}
.mini a,.mini button{flex:1;text-align:center;background:transparent;color:var(--texto);border:1px solid var(--linha);border-radius:10px;
padding:8px;font:inherit;font-size:13px;font-weight:700;cursor:pointer;text-decoration:none}
.vazio{background:var(--papel);border:1px dashed var(--linha);border-radius:18px;padding:22px;color:var(--fraco)}
.aviso{background:#2a2010;border:1px solid #5a4313;color:var(--aviso);border-radius:14px;padding:14px 16px;margin:16px 0 0}
.aviso ol{margin:6px 0 0 18px;padding:0;color:var(--texto)}
.rodando{background:#102a1b;border:1px solid #1d5a37;color:var(--ok);border-radius:14px;padding:12px 16px;margin:16px 0 0}
details.extra{margin-top:30px;color:var(--fraco)}
details.extra summary{cursor:pointer}
details.extra button{background:transparent;color:var(--texto);border:1px solid var(--linha);border-radius:10px;padding:8px 12px;font:inherit;cursor:pointer;margin:8px 8px 0 0}
pre{background:#000;border:1px solid var(--linha);border-radius:12px;padding:12px;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow:auto;font-size:12px}
details.conferir{background:var(--papel);border:1px solid var(--linha);border-radius:18px;padding:14px 16px;margin:16px 0 0}
details.conferir summary{cursor:pointer;font-weight:900;font-size:17px}
.dica{color:var(--fraco);font-size:13px;margin:8px 0 10px}
.dica a{color:var(--texto)}
.form-conferir{display:flex;flex-direction:column;gap:10px;align-items:flex-start}
.form-conferir textarea,.form-conferir input,.form-conferir select{width:100%;background:#000;color:var(--texto);border:1px solid var(--linha);border-radius:12px;
padding:10px;font:13px/1.45 ui-monospace,Consolas,monospace;resize:vertical}
.res{list-style:none;margin:14px 0 0;padding:0;display:flex;flex-direction:column;gap:8px}
.res li{display:grid;grid-template-columns:28px 1fr auto;gap:10px;align-items:center;background:var(--papel2);
border:1px solid var(--linha);border-radius:12px;padding:10px 12px}
.res .ic{font-size:20px;font-weight:900;text-align:center}
.res .r-ok .ic{color:var(--ok)}.res .r-aviso .ic{color:var(--aviso)}.res .r-erro .ic{color:var(--brasa)}
.res .txt p{margin:0}
.res .lk{color:var(--fraco);font-size:12px;word-break:break-all}
.res .mini{min-width:150px}
@media (max-width:600px){.res li{grid-template-columns:24px 1fr}.res .mini{grid-column:2}}
code{background:#000;padding:1px 6px;border-radius:5px}
"""

JS = """
async function copiar(t){try{await navigator.clipboard.writeText(t);return true}catch(e){
  const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
  document.execCommand('copy');a.remove();return true}}
document.querySelectorAll('[data-copiar]').forEach(b=>b.addEventListener('click',async()=>{
  await copiar(b.dataset.copiar);const antes=b.textContent;b.textContent='Copiado ✓';b.classList.add('feito');
  setTimeout(()=>{b.textContent=antes;b.classList.remove('feito')},1500)}));
{const aba=new URLSearchParams(location.search).get('aba');
  if(aba==='conferir'||aba==='postagem'){const c=document.getElementById(aba);if(c){c.open=true;c.scrollIntoView()}}}
document.querySelectorAll('.chips button').forEach(ch=>ch.addEventListener('click',()=>{
  document.querySelectorAll('.chips button').forEach(x=>x.classList.remove('ativo'));ch.classList.add('ativo');
  const tag=ch.dataset.tag;document.querySelectorAll('.card').forEach(c=>{c.hidden=!!tag&&c.dataset.tag!==tag})}));
"""


_INICIOS_MOTIVO = ("PAROU", "FALHOU", "Faltam credenciais", "RESULTADO", "NAO RODEI", "ATENCAO")


def _motivo(saida: str) -> str:
    """A linha que explica o que deu errado, em portugues, para mostrar no topo da tela."""
    linhas = [ln.strip() for ln in (saida or "").splitlines() if ln.strip()]
    for ln in reversed(linhas):
        if ln.startswith(_INICIOS_MOTIVO) or "] " in ln and "FALHOU" in ln:
            return ln.split("->", 1)[-1].strip() if "->" in ln else ln
    return linhas[-1] if linhas else ""


def _ler_achados(modo: str) -> dict | None:
    import json
    arq = SAIDA / ("demo/ultima" if modo == "demo" else "ultima") / "achados.json"
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ler_conferencia() -> dict | None:
    """O resultado do ultimo "Conferir links" (gravado por `python -m robo conferir`). Arquivo de
    outra versao volta marcado como `antigo` (40a rodada): os links sao reaproveitados para conferir
    de novo, mas nenhum resultado dele vai para a tela."""
    import json
    try:
        dados = json.loads((SAIDA / "conferencia.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(dados, dict) or not isinstance(dados.get("resultados"), list):
        return None
    if dados.get("versao") != VERSAO_CONFERENCIA:
        links = [str(r.get("link")) for r in dados["resultados"] if isinstance(r, dict) and r.get("link")]
        return {"antigo": True, "links": links[:MAX_LINKS_COLADOS], "resultados": []}
    return dados


_CLASSE_EXAME = {"ok": "r-ok", "aviso": "r-aviso", "erro": "r-erro", "espera": "r-aviso"}


def _ler_postagens() -> list[dict]:
    """As ultimas postagens montadas (gravadas por `python -m robo postagem`); so da versao atual."""
    import json
    try:
        dados = json.loads((SAIDA / "postagens.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dados, dict) or dados.get("versao") != VERSAO_POSTAGEM:
        return []
    return [p for p in (dados.get("postagens") or []) if isinstance(p, dict)][:MAX_POSTAGENS]


def _secao_postagem(est: dict) -> str:
    """Caixa "Montar postagem": link gerado a mao + preco -> mensagem pronta, so com o link
    conferido (nivel OK) e o produto fora dos bloqueios. Tudo o que vem do arquivo e escapado."""
    e = html.escape
    rodando = est["rodando"]
    cfg_tags = {}
    try:
        cfg_tags = {k: v for k, v in (ler_nicho().get("tags") or {}).items()
                    if not k.startswith("_") and isinstance(v, dict)}
    except Exception:  # noqa: BLE001 - config estragada nao derruba a tela
        cfg_tags = {}
    opcoes = "".join(f'<option value="{e(k)}"{" selected" if k == "maternidade" else ""}>'
                     f'{e(str(v.get("emoji", "")))} {e(str(v.get("rotulo", k)))}</option>' for k, v in cfg_tags.items())
    cartoes = []
    for p in _ler_postagens():
        quando = ""
        try:
            quando = datetime.fromisoformat(str(p.get("quando"))).strftime("%d/%m %H:%M")
        except ValueError:
            pass
        if p.get("ok") is True and isinstance(p.get("mensagem"), str):
            avisos = "".join(f'<p class="aviso-card">⚠ {e(str(a))}</p>' for a in (p.get("avisos") or []))
            link = str(p.get("link") or "")
            abrir = (f'<a href="{e(link)}" target="_blank" rel="noopener noreferrer">Abrir</a>'
                     if endereco_seguro(link) else "")
            cartoes.append(f"""<li class="r-ok"><span class="ic">✓</span><div class="txt">
<p><b>{e(str(p.get("emoji", "")))} {e(str(p.get("nome", "")))}</b> · {e(reais(p["preco"]) if isinstance(p.get("preco"), (int, float)) else "")}</p>
<p class="lk">{e(quando)} · link conferido · confira o preço no app antes de postar</p>{avisos}</div>
<div class="mini"><button type="button" data-copiar="{e(p["mensagem"])}">Copiar mensagem</button>
<button type="button" data-copiar="{e(str(p.get("mensagem_feed", "")))}">Feed</button>{abrir}</div></li>""")
        else:
            motivos = "".join(f"<p>{e(str(m))}</p>" for m in (p.get("motivos") or ["não montou"]))
            cartoes.append(f"""<li class="r-erro"><span class="ic">✗</span><div class="txt">{motivos}
<p class="lk">{e(quando)} · {e(str(p.get("link") or ""))}</p></div><div></div></li>""")
    andando = (f'<div class="rodando">Montando a postagem… {int(time.time() - est["inicio"])}s</div>'
               if rodando == "postagem" else "")
    aviso = f'<p class="aviso-card">{e(est["aviso_postagem"])}</p>' if est.get("aviso_postagem") else ""
    trava = " disabled" if rodando else ""
    return f"""<details class="conferir" id="postagem" open><summary>Montar postagem</summary>
<p class="dica">Achou a promoção na Shopee? Gere o link no <a href="https://affiliate.shopee.com.br/" target="_blank"
rel="noopener noreferrer">painel de afiliados</a> (<b>Link personalizado</b>), cole aqui com o preço que está vendo e o robô
confere o link e monta a mensagem. Mamadeira, bico, chupeta e fórmula são barrados (NBCAL).</p>
<form method="post" action="/postagem" class="form-conferir">
<input name="link" required maxlength="600" placeholder="Link de afiliado: https://s.shopee.com.br/…">
<input name="preco" required maxlength="20" inputmode="decimal" placeholder="Preço agora, ex.: 29,90">
<input name="nome" maxlength="150" placeholder="Nome do produto (só se o link não trouxer)">
<select name="tag">{opcoes}</select>
<button class="atualizar"{trava}>Montar postagem</button></form>
{aviso}{andando}{f'<ul class="res">{"".join(cartoes)}</ul>' if cartoes else ""}
</details>"""


def _secao_conferir(est: dict) -> str:
    """Caixa "Conferir links": cola links gerados a mao no painel de afiliados e ve para onde levam.
    Tudo o que vem do arquivo e escapado; "Abrir" so existe para link https da Shopee."""
    e = html.escape
    rodando = est["rodando"]
    conf = _ler_conferencia()
    linhas, colados = [], []
    for r in (conf or {}).get("resultados", [])[:MAX_LINKS_COLADOS]:
        if not isinstance(r, dict) or r.get("estado") not in ESTADOS_EXAME:
            continue
        link = str(r.get("link") or "")
        colados.append(link)
        abrir = (f'<a href="{e(link)}" target="_blank" rel="noopener noreferrer">Abrir</a>'
                 if endereco_seguro(link) else "")
        nivel = nivel_do_exame(r)
        linhas.append(f"""<li class="{_CLASSE_EXAME[nivel]}"><span class="ic">{ICONES[nivel]}</span>
<div class="txt"><p>{e(texto_do_exame(r))}</p><p class="lk">{e(link)}</p></div>
<div class="mini"><button type="button" data-copiar="{e(link)}">Copiar</button>{abrir}</div></li>""")
    quando = ""
    if conf and conf.get("quando"):
        try:
            quando = datetime.fromisoformat(str(conf["quando"])).strftime(" · conferido %d/%m às %H:%M")
        except ValueError:
            quando = ""
    resultado = (f'<ul class="res">{"".join(linhas)}</ul>' if linhas else "")
    if conf and conf.get("antigo"):
        colados = list(conf.get("links") or [])
        resultado = ('<p class="aviso-card">A última conferência foi feita por uma versão anterior do robô. '
                     'Os links estão na caixa: clique em <b>Conferir links</b> para conferir de novo.</p>')
    aviso = f'<p class="aviso-card">{e(est["aviso_conferir"])}</p>' if est.get("aviso_conferir") else ""
    andando = (f'<div class="rodando">Conferindo {est["qtd_links"]} link(s) na Shopee… '
               f'{int(time.time() - est["inicio"])}s</div>') if rodando == "conferir" else ""
    trava = " disabled" if rodando else ""
    aberto = " open" if (linhas or aviso or andando or not ler_env().get("SHOPEE_APP_ID")) else ""
    return f"""<details class="conferir" id="conferir"{aberto}><summary>Conferir links{e(quando)}</summary>
<p class="dica">Gere os links no <a href="https://affiliate.shopee.com.br/" target="_blank" rel="noopener noreferrer">painel
de afiliados</a> (<b>Link personalizado</b>) e cole aqui, um por linha (até {MAX_LINKS_COLADOS}). O robô abre cada um na
Shopee e diz para onde ela leva o link (o produto e o nome que estão no endereço) e se ela põe a marcação de afiliado.
Se o produto existe e está à venda, só abrindo para ver.</p>
<form method="post" action="/conferir" class="form-conferir">
<textarea name="links" rows="4" maxlength="12000" placeholder="https://s.shopee.com.br/…">{e(chr(10).join(colados))}</textarea>
<button class="atualizar"{trava}>Conferir links</button></form>
{aviso}{andando}{resultado}
</details>"""


def _card(a: dict) -> str:
    e = html.escape
    foto = (f'<img src="{e(a["imagem"])}" alt="" loading="lazy" referrerpolicy="no-referrer">' if a.get("imagem")
            else f'<div class="semfoto">{e(a.get("emoji", "🛍️"))}</div>')
    pct = f'<span class="pct">-{a["queda_pct"]}%</span>' if a.get("comprovado") else ""
    selo = '<span class="selo">⚡ CAIU FORTE</span>' if a.get("relampago") else (
        f'<span class="selo">{e(a["selo"])}</span>' if a.get("selo") else "")
    variacoes = bool(a.get("variacoes"))
    if a.get("comprovado"):
        rotulo_de = "Opção mais barata: de" if variacoes else "De"
        de = f'<p class="de"><span class="sem-risco">{rotulo_de}</span> <s>{e(reais(a["preco_de"]))}</s></p>'
    else:
        de = ""
    a_partir = '<span class="apartir">a partir de</span>' if variacoes else ""
    aviso = f'<p class="aviso-card">⚠ {e(a["aviso"])}</p>' if a.get("aviso") else ""
    if a.get("link_conferido"):
        aviso += '<p class="conferido">✓ link conferido: abre o produto na Shopee</p>'
    prova = []
    if a.get("nota") is not None:
        prova.append(f'⭐ {str(round(a["nota"], 1)).replace(".", ",")}')
    if a.get("vendas"):
        prova.append(f'{e(milhar(a["vendas"]))} vendidos')
    link = a.get("link") or ""
    return f"""<article class="card" data-tag="{e(a['tag'])}">
<div class="foto">{foto}{pct}{selo}</div>
<div class="corpo">
<p class="nome" title="{e(a.get('titulo', ''))}">{e(a['emoji'])} {e(a['nome'])}</p>
{de}<p class="por">{a_partir}{e(reais(a['preco_por']))}</p>
<p class="prova">{' · '.join(prova)}</p>
{aviso}
<button type="button" class="copiar" data-copiar="{e(a['mensagem'])}">Copiar mensagem</button>
<div class="mini"><button type="button" data-copiar="{e(link)}">Link</button>
<button type="button" data-copiar="{e(a['mensagem_feed'])}">Feed</button>
<a href="{e(link)}" target="_blank" rel="noopener noreferrer">Abrir</a></div>
</div></article>"""


def _pagina(modo: str = "") -> str:
    e = html.escape
    env = ler_env()
    tem_cred = bool(env.get("SHOPEE_APP_ID") and env.get("SHOPEE_SECRET"))
    modo = modo if modo in ("demo", "real") else ("real" if (SAIDA / "ultima" / "achados.json").exists() else "demo")
    dados = _ler_achados(modo) or {"achados": [], "quando": None}
    with _trava:
        est = dict(_estado)
    rodando = est["rodando"]
    lista = dados.get("achados", [])
    comprovados = [a for a in lista if a.get("comprovado")]
    novos = [a for a in lista if not a.get("comprovado")]
    quando = dados.get("quando")
    quando_txt = (datetime.fromisoformat(quando).strftime("atualizado %d/%m às %H:%M") if quando else "ainda não atualizado")
    origem = "DEMONSTRAÇÃO (produtos fictícios)" if modo == "demo" else "sua conta Shopee"
    acao = "rodar" if tem_cred else "demo"
    rotulo = "Atualizar achados" if tem_cred else "Atualizar (demonstração)"
    trava = " disabled" if rodando else ""
    tags = []
    for a in lista:
        if a["tag"] not in [t[0] for t in tags]:
            tags.append((a["tag"], a["emoji"], a["rotulo"]))
    chips = ['<button type="button" class="ativo" data-tag="">Todos</button>'] + [
        f'<button type="button" data-tag="{e(t)}">{e(em)} {e(r)}</button>' for t, em, r in tags]
    if comprovados:
        bloco1 = f'<h2>Desconto comprovado · {len(comprovados)}</h2><div class="grade">{"".join(_card(a) for a in comprovados)}</div>'
    else:
        bloco1 = ('<h2>Desconto comprovado</h2><div class="vazio">Nenhum ainda. O "de/por" só aparece quando o robô '
                  'já acompanhou o preço por alguns dias e viu a queda de verdade. Atualize umas 3 vezes por dia na '
                  'primeira semana.</div>')
    bloco2 = (f'<h2>Novidades (sem histórico ainda: só o preço atual) · {len(novos)}</h2>'
              f'<div class="grade">{"".join(_card(a) for a in novos)}</div>') if novos else ""
    aviso = "" if tem_cred else """<div class="aviso"><b>Para usar com a conta dela:</b><ol>
<li>No computador, abra <a href="https://affiliate.shopee.com.br/open_api" target="_blank" rel="noopener noreferrer"
style="color:var(--texto)">affiliate.shopee.com.br/open_api</a>. Se aparecer o botão laranja <b>Aplicar</b>, clique
e copie o <b>ID</b> e a <b>senha (token)</b>. Se não aparecer, peça a liberação (grátis) no
<a href="https://help.shopee.com.br/portal/webform/bbce78695c364ba18c9cbceb74ec9091" target="_blank"
rel="noopener noreferrer" style="color:var(--texto)">formulário da Shopee</a> e aguarde o e-mail.</li>
<li>Abra o arquivo <code>W:\\Robo Shopee\\.env</code> no Bloco de Notas e cole: <code>SHOPEE_APP_ID=</code> o ID e
<code>SHOPEE_SECRET=</code> a senha. Salve.</li>
<li>Aqui embaixo, em <b>Mais opções</b>, clique em <b>Testar conexão com a Shopee</b>.</li></ol></div>"""
    status = (f'<div class="rodando">Buscando ofertas… {int(time.time() - est["inicio"])}s '
              f'(pode levar uns minutos)</div>') if rodando and rodando not in ("conferir", "postagem") else ""
    # postagem que nao montou sai com codigo 1, mas o motivo ja aparece na propria caixa
    if not rodando and est["codigo"] not in (None, 0) and est["ultimo"] != "postagem":
        titulo = ("A conferência dos links não deu certo." if est["ultimo"] == "conferir"
                  else "A última atualização não deu certo.")
        status = (f'<div class="aviso"><b>{titulo}</b><br>'
                  f'{e(_motivo(est["saida"]) or "código " + str(est["codigo"]))}</div>')
    recarregar = '<meta http-equiv="refresh" content="3">' if rodando else ""
    outros = []
    for nome, (rot, _) in COMANDOS.items():
        des = " disabled" if rodando or (nome in ("diagnostico", "rodar") and not tem_cred) else ""
        outros.append(f'<form method="post" action="/executar/{nome}"><button{des}>{e(rot)}</button></form>')
    troca = ('<a href="/?modo=demo" style="color:var(--fraco)">ver demonstração</a>' if modo == "real"
             else ('<a href="/?modo=real" style="color:var(--fraco)">ver achados reais</a>'
                   if (SAIDA / "ultima" / "achados.json").exists() else ""))
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{recarregar}
<title>Achadinhos de hoje</title><style>{CSS}</style></head><body>
<div class="topo"><div class="in">
<div><h1>Achadinhos <em>de hoje</em></h1><div class="quando">{e(quando_txt)} · {e(origem)} {troca}</div></div>
<div class="esp"></div>
<form method="post" action="/executar/{acao}"><button class="atualizar"{trava}>{e(rotulo)}</button></form>
</div></div>
<nav class="chips">{''.join(chips)}</nav>
<main>
{aviso}{status}
{_secao_postagem(est)}
{_secao_conferir(est)}
{bloco1}
{bloco2}
<details class="extra"><summary>Mais opções e detalhes técnicos</summary>
<div>{''.join(outros)}</div>
<pre>{e(est["saida"] or "nada rodou ainda nesta sessão")}</pre>
</details>
</main><script>{JS}</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    timeout = 15  # 39a rodada: conexao que nao manda o corpo nao prende a linha para sempre

    def log_message(self, *_):  # silencioso no console
        pass

    def _responder(self, corpo: bytes, tipo: str = "text/html; charset=utf-8", status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self._cabecalhos_seguranca()
        self.end_headers()
        self.wfile.write(corpo)

    def _cabecalhos_seguranca(self):
        # 29a rodada do Codex: nada de ser enquadrado por outro site (clickjacking)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _origem_confiavel(self, exigir_origem: bool) -> bool:
        """So o proprio painel conversa com ele: Host local (contra DNS rebinding) e, no POST,
        Origin/Referer do proprio painel (contra um site qualquer mandar "rodar" - CSRF)."""
        locais = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
        if self.headers.get("Host", "") not in locais:
            return False
        if not exigir_origem:
            return True
        origem = self.headers.get("Origin") or ""
        if origem:
            return origem in {f"http://{h}" for h in locais}
        # sem Origin: Referer comparado pela ORIGEM exata (29a rodada: o prefixo aceitava :80310)
        partes = urlsplit(self.headers.get("Referer") or "")
        return partes.scheme == "http" and partes.netloc in locais

    def do_GET(self):  # noqa: N802
        if not self._origem_confiavel(exigir_origem=False):
            return self._responder(b"proibido", "text/plain", 403)
        if self.path.split("?")[0] in ("/", "/index.html"):
            modo = "demo" if "modo=demo" in self.path else ("real" if "modo=real" in self.path else "")
            return self._responder(_pagina(modo).encode("utf-8"))
        if self.path in ("/vitrine/real", "/vitrine/demo"):
            arq = SAIDA / ("ultima" if self.path.endswith("real") else "demo/ultima") / "vitrine.html"
            if arq.exists():
                return self._responder(arq.read_bytes())
            return self._responder("Ainda não há vitrine. Rode primeiro.".encode("utf-8"), status=404)
        return self._responder(b"nao encontrado", "text/plain", 404)

    def _ler_corpo(self, tamanho: int) -> bytes | None:
        """O corpo inteiro dentro de PRAZO_CORPO segundos no TOTAL (nao so por pedaco); None se
        nao chegar a tempo ou a conexao fechar antes."""
        fim = time.monotonic() + PRAZO_CORPO
        partes, falta = [], tamanho
        try:
            while falta > 0:
                restante = fim - time.monotonic()
                if restante <= 0:
                    return None
                self.connection.settimeout(restante)
                pedaco = self.rfile.read1(min(falta, 65536))
                if not pedaco:
                    return None
                partes.append(pedaco)
                falta -= len(pedaco)
        except OSError:  # inclui o timeout
            return None
        finally:
            try:
                self.connection.settimeout(self.timeout)
            except OSError:
                pass
        return b"".join(partes)

    def _ler_campo(self, campo: str) -> str | None:
        """Um campo do formulario (x-www-form-urlencoded). None se o corpo passar do limite ou nao
        chegar inteiro a tempo."""
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if tamanho < 0 or tamanho > LIMITE_CORPO:
            return None
        corpo = self._ler_corpo(tamanho) if tamanho else b""
        if corpo is None:
            return None
        return parse_qs(corpo.decode("utf-8", "replace"), keep_blank_values=True).get(campo, [""])[0]

    def _conferir(self):
        """POST /conferir: tira os links do texto colado e roda `python -m robo conferir LINKS...`
        no mesmo esquema dos outros botoes (um de cada vez, processo separado, sem shell)."""
        texto = self._ler_campo("links")
        links = links_do_texto(texto) if texto is not None else []
        if texto is None:
            aviso = (f"Não consegui ler o texto colado (grande demais ou chegou incompleto): cole até "
                     f"{MAX_LINKS_COLADOS} links por vez e tente de novo.")
        elif not links:
            aviso = "Não achei nenhum link no texto colado (o link começa com https://s.shopee.com.br/…)."
        elif reservar("conferir"):
            aviso = ""
            with _trava:
                _estado.update(qtd_links=len(links), aviso_conferir="")
            threading.Thread(target=_executar, args=("conferir", ["conferir", *links]), daemon=True).start()
            time.sleep(0.3)
        else:
            aviso = "Já tem outra ação rodando; espere terminar e confira de novo."
        if aviso:
            with _trava:
                _estado["aviso_conferir"] = aviso
        self.send_response(303)
        # sem '#': com '#conferir' a recarga automatica virava so um pulo na pagina e o
        # "Conferindo..." ficava parado (achado no teste da tela em 20/10)
        self.send_header("Location", "/?aba=conferir")
        self._cabecalhos_seguranca()
        self.end_headers()

    def _ler_formulario(self) -> dict | None:
        """Todos os campos do formulario (x-www-form-urlencoded), com o mesmo limite e prazo total."""
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if tamanho < 0 or tamanho > LIMITE_CORPO:
            return None
        corpo = self._ler_corpo(tamanho) if tamanho else b""
        if corpo is None:
            return None
        return {k: v[0] for k, v in parse_qs(corpo.decode("utf-8", "replace"), keep_blank_values=True).items()}

    def _postagem(self):
        """POST /postagem: link + preco (+ nome, tag) viram `python -m robo postagem ...` (lista, sem
        shell, um de cada vez). O link e o primeiro link valido do campo (links_do_texto)."""
        campos = self._ler_formulario()
        aviso = ""
        if campos is None:
            aviso = "Não consegui ler o formulário (grande demais ou chegou incompleto). Tente de novo."
        else:
            links = links_do_texto(campos.get("link", ""), limite=1)
            preco = " ".join(campos.get("preco", "").split())[:20]
            nome = " ".join(campos.get("nome", "").split())[:150]
            tag = campos.get("tag", "maternidade")[:40]
            if not links:
                aviso = "Cole o link de afiliado (começa com https://s.shopee.com.br/…)."
            elif not preco:
                aviso = "Digite o preço que está na Shopee, por exemplo 29,90."
            elif reservar("postagem"):
                args = ["postagem", "--link", links[0], "--preco", preco, "--tag", tag]
                if nome:
                    args += ["--nome", nome]
                threading.Thread(target=_executar, args=("postagem", args), daemon=True).start()
                time.sleep(0.3)
            else:
                aviso = "Já tem outra ação rodando; espere terminar e tente de novo."
        with _trava:
            _estado["aviso_postagem"] = aviso
        self.send_response(303)
        self.send_header("Location", "/?aba=postagem")
        self._cabecalhos_seguranca()
        self.end_headers()

    def do_POST(self):  # noqa: N802
        if not self._origem_confiavel(exigir_origem=True):
            # le o corpo pequeno antes de recusar: fechar com dados nao lidos vira conexao anulada no
            # Windows e o cliente nem ve o 403 (teste intermitente em 26/10); nada do corpo e usado
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                tamanho = 0
            if 0 < tamanho <= LIMITE_CORPO:
                self._ler_corpo(tamanho)
            return self._responder(b"proibido", "text/plain", 403)
        if self.path == "/conferir":
            return self._conferir()
        if self.path == "/postagem":
            return self._postagem()
        nome = self.path.rsplit("/", 1)[-1]
        if self.path.startswith("/executar/") and nome in COMANDOS:
            if reservar(nome):
                threading.Thread(target=_executar, args=(nome,), daemon=True).start()
                time.sleep(0.3)
        self.send_response(303)
        self.send_header("Location", "/")
        self._cabecalhos_seguranca()
        self.end_headers()


class _Servidor(ThreadingHTTPServer):
    """A porta e SO do painel. No Windows o padrao (SO_REUSEADDR) deixava subir DOIS paineis na mesma
    porta (dois cliques no PAINEL.bat), e o navegador falava com qualquer um (teste de 20/10)."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: ninguem mais escuta nesta porta
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _painel_ja_aberto(url: str) -> bool | None:
    """True = o painel ja responde neste endereco; False = a porta e de OUTRO programa;
    None = ninguem respondeu."""
    try:
        with urllib.request.urlopen(url + "/", timeout=3) as r:
            return "Achadinhos de hoje" in r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError:
        return False
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    """`--abrir` (o PAINEL.bat usa) abre o navegador so DEPOIS de o painel estar escutando (antes,
    o navegador abria primeiro e a pagina aparecia "fora do ar"). Se o painel ja estiver aberto,
    so abre o navegador nele, sem erro."""
    abrir = "--abrir" in (sys.argv[1:] if argv is None else argv)
    url = f"http://127.0.0.1:{PORTA}"
    try:
        servidor = _Servidor(("127.0.0.1", PORTA), _Handler)
    except OSError:
        situacao = _painel_ja_aberto(url)
        if situacao:
            print(f"O painel já está aberto: {url}", flush=True)
            if abrir:
                webbrowser.open(url)
            return 0
        print(f"A porta {PORTA} está ocupada por outro programa; o painel não abriu.", flush=True)
        return 2
    print(f"Painel no ar: {url}  - deixe esta janela aberta enquanto usa (fechar a janela desliga o painel).",
          flush=True)
    if abrir:
        webbrowser.open(url)  # o servidor ja escuta: o pedido do navegador espera na fila
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
