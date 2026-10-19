"""Saidas da rodada: vitrine.html (para ela escolher no celular/PC), ofertas.csv,
legendas.txt (stories/WhatsApp, com link), legendas_feed.txt (sem link) e ofertas.json."""
from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .curadoria import Candidato, comissao_reais
from .texto import AVISO_FIM, _nfkc, legenda, linha_preco, milhar, nome_curto, reais, sem_numeros, tem_alegacao

COR_STATUS = {"menor_preco": "ok", "queda_real": "ok", "sem_historico": "neutro"}


def url_segura(u: str) -> str:
    """So https — dado vindo da API nunca vira javascript:/data: na pagina."""
    u = (u or "").strip()
    return u if u.lower().startswith("https://") else ""


def celula_segura(v):
    """Excel executa celula que comeca com = + - @ (injecao de formula via nome de loja)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _e(t) -> str:
    return html.escape(str(t if t is not None else ""), quote=True)


def _cfg_leg(cfg: dict) -> dict:
    leg = cfg.get("legenda", {})
    return {"cupom": leg.get("cupom_do_dia", ""), "hashtags": leg.get("hashtags")}


def _card(c: Candidato, emoji: str, rotulo: str, quando: datetime, top: bool, cfg: dict) -> str:
    o, v = c.oferta, c.veredito
    img = url_segura(o.imagem)
    link = url_segura(c.link)
    kw = _cfg_leg(cfg)
    leg = legenda(c, emoji, "link", **kw)
    leg_feed = legenda(c, emoji, "feed", **kw)
    extras = []
    if o.nota is not None:
        extras.append(f"★ {str(round(o.nota, 1)).replace('.', ',')}")
    if o.vendas:
        extras.append(f"{milhar(o.vendas)} vendidos")
    cr = comissao_reais(o)
    if cr is not None:
        extras.append(f"comissão ~{reais(cr)}/venda")
    if v.confirmado and v.preco_normal:
        ref = f"normal: {reais(v.preco_normal)} (histórico de {round(v.dias_historico)} dias)"
    elif o.preco_de_estimado:
        ref = f"Shopee diz -{o.desconto}% (de ~{reais(o.preco_de_estimado)}): não confirmado"
    else:
        ref = ""
    avisos = []
    if c.aviso:
        avisos.append(f"⚠ {c.aviso}")
    if not c.reconferido and cfg.get("coleta", {}).get("reconferir_escolhidos", True):
        avisos.append("⚠ preço não reconferido nesta rodada")
    titulo_n = _nfkc(o.nome)
    if tem_alegacao(sem_numeros(titulo_n)) or re.search(r"[%$]|\boff\b", titulo_n, re.IGNORECASE):
        avisos.append("título do vendedor tinha alegação de preço/promoção: foi cortado na legenda")
    if any(ch.isdigit() for ch in o.nome):
        avisos.append("números do título (quantidade/medida) não vão para a legenda: confira no link")
    if not c.link_rastreado:
        avisos.append("link sem subId (não aparece separado no painel)")
    selos = []
    if c.selo:
        selos.append(f'<span class="selo novo">{_e(c.selo)}</span>')
    if v.queda_brusca and v.confirmado:
        selos.append('<span class="selo relampago">⚡ caiu forte</span>')
    selo_off = (f'<span class="off">-{round(v.queda_real * 100)}%</span>' if v.confirmado and v.queda_real
                else '<span class="off neutro">a confirmar</span>')
    foto = (f'<img src="{_e(img)}" alt="" loading="lazy" referrerpolicy="no-referrer">' if img
            else '<div class="semfoto">sem foto</div>')
    return f"""
<article class="card" data-tag="{_e(c.tag)}" data-top="{1 if top else 0}">
  <div class="foto">{foto}{selo_off}<div class="selos">{''.join(selos)}</div></div>
  <div class="corpo">
    <p class="tagline">{_e(emoji)} {_e(rotulo)} · {_e(o.loja)}</p>
    <h2>{_e(o.nome[:140])}</h2>
    <p class="na-legenda">na legenda: <b>{_e(nome_curto(o.nome))}</b></p>
    <p class="preco">{_e(linha_preco(c).split(' (')[0])}</p>
    {f'<p class="de">{_e(ref)}</p>' if ref else ''}
    <p class="veredito {COR_STATUS.get(v.status, 'neutro')}">{_e(v.rotulo)}</p>
    <p class="extras">{_e(' · '.join(extras))}</p>
    <p class="lido">preço lido às {_e(quando.strftime('%H:%M de %d/%m'))}</p>
    {''.join(f'<p class="aviso">{_e(a)}</p>' for a in avisos)}
    <div class="acoes">
      <button type="button" data-copiar="{_e(leg)}">Copiar legenda</button>
      <button type="button" data-copiar="{_e(link)}">Copiar link</button>
      <button type="button" data-compartilhar="{_e(leg)}">Compartilhar</button>
      <button type="button" data-copiar="{_e(leg_feed)}">Texto p/ feed</button>
      {f'<a href="{_e(img)}" target="_blank" rel="noopener noreferrer">Foto</a>' if img else ''}
      {f'<a href="{_e(link)}" target="_blank" rel="noopener noreferrer">Abrir</a>' if link else ''}
    </div>
  </div>
</article>"""


CSS = """
:root{--fundo:#0d0b0c;--papel:#171315;--linha:#2c2427;--texto:#f6efe9;--fraco:#a99c97;
--brasa:#ff4d2e;--ok:#34d27b;--ruim:#ff6b6b;--neutro:#f2c14e}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--fundo);color:var(--texto);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:28px 16px 12px;max-width:1200px;margin:0 auto}
h1{font-size:clamp(34px,7vw,64px);line-height:.95;margin:0 0 10px;letter-spacing:-.03em;font-weight:900}
h1 em{color:var(--brasa);font-style:normal}
.sub{color:var(--fraco);margin:0 0 16px}
.chips{display:flex;gap:8px;flex-wrap:wrap;padding:0 16px;max-width:1200px;margin:0 auto 18px}
.chips button{background:var(--papel);color:var(--texto);border:1px solid var(--linha);border-radius:999px;padding:8px 14px;font:inherit;cursor:pointer}
.chips button.ativo{background:var(--brasa);border-color:var(--brasa);color:#160604;font-weight:800}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;padding:0 16px 40px;max-width:1200px;margin:0 auto}
.card{background:var(--papel);border:1px solid var(--linha);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.card[hidden]{display:none}
.foto{position:relative;aspect-ratio:1;background:#221c1e}
.foto img{width:100%;height:100%;object-fit:cover;display:block}
.semfoto{display:grid;place-items:center;height:100%;color:var(--fraco)}
.off{position:absolute;top:10px;left:10px;background:var(--brasa);color:#160604;font-weight:900;font-size:22px;padding:4px 10px;border-radius:8px;transform:rotate(-4deg)}
.off.neutro{background:var(--neutro);font-size:14px}
.selos{position:absolute;bottom:10px;left:10px;display:flex;gap:6px;flex-wrap:wrap}
.selo{background:#000c;color:var(--neutro);font-weight:800;font-size:12px;padding:3px 8px;border-radius:6px;letter-spacing:.03em}
.selo.novo{color:var(--ok)}
.corpo{padding:12px 14px 14px;display:flex;flex-direction:column;gap:4px;flex:1}
.tagline{margin:0;color:var(--fraco);font-size:12px;text-transform:uppercase;letter-spacing:.06em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
h2{font-size:16px;margin:2px 0 4px;line-height:1.25}
.preco{margin:0;font-size:22px;font-weight:900}
.de,.lido,.na-legenda{margin:0;color:var(--fraco);font-size:12px}
.na-legenda b{color:var(--texto);font-weight:600}
.veredito{margin:6px 0 0;font-weight:700;font-size:13px}
.veredito.ok{color:var(--ok)}.veredito.ruim{color:var(--ruim)}.veredito.neutro{color:var(--neutro)}
.extras{margin:0;color:var(--fraco);font-size:13px}
.aviso{margin:2px 0 0;color:var(--neutro);font-size:12px}
.acoes{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:auto;padding-top:10px}
.acoes button,.acoes a{text-align:center;background:transparent;color:var(--texto);border:1px solid var(--linha);border-radius:9px;padding:9px 6px;font:inherit;font-size:13px;font-weight:700;cursor:pointer;text-decoration:none}
.acoes button:first-child{background:var(--brasa);border-color:var(--brasa);color:#160604}
.acoes button:hover,.acoes a:hover{border-color:var(--brasa)}
.acoes button.feito{background:var(--ok);color:#04150b;border-color:var(--ok)}
details{max-width:1200px;margin:0 auto 40px;padding:0 16px;color:var(--fraco)}
details li{margin:2px 0}
footer{max-width:1200px;margin:0 auto;padding:0 16px 40px;color:var(--fraco);font-size:13px}
"""

JS = """
async function copiar(t){try{await navigator.clipboard.writeText(t)}catch(e){const a=document.createElement('textarea');
  a.value=t;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()}}
function feito(b){const antes=b.textContent;b.textContent='Copiado ✓';b.classList.add('feito');
  setTimeout(()=>{b.textContent=antes;b.classList.remove('feito')},1400)}
document.querySelectorAll('[data-copiar]').forEach(b=>b.addEventListener('click',async()=>{
  await copiar(b.getAttribute('data-copiar'));feito(b)}));
document.querySelectorAll('[data-compartilhar]').forEach(b=>b.addEventListener('click',async()=>{
  const t=b.getAttribute('data-compartilhar');
  if(navigator.share){try{await navigator.share({text:t});return}catch(e){if(e.name==='AbortError')return}}
  await copiar(t);feito(b)}));
function filtrar(tag){document.querySelectorAll('.card').forEach(c=>{
  c.hidden = tag==='top' ? c.dataset.top!=='1' : (!!tag && c.dataset.tag!==tag)})}
document.querySelectorAll('.chips button').forEach(ch=>ch.addEventListener('click',()=>{
  document.querySelectorAll('.chips button').forEach(x=>x.classList.remove('ativo'));ch.classList.add('ativo');
  filtrar(ch.dataset.tag)}));
filtrar(document.querySelector('.chips button.ativo')?.dataset.tag||'');
"""


def gerar_html(escolhidos: dict[str, list[Candidato]], recusados: Counter, cfg: dict,
               quando: datetime, resumo: dict, top: list[Candidato] | None = None) -> str:
    tags_cfg = cfg["tags"]
    top = top or []
    ids_top = {id(c) for c in top}
    total = sum(len(v) for v in escolhidos.values())
    chips = []
    if top:
        chips.append(f'<button type="button" class="ativo" data-tag="top">⭐ Top {len(top)} do dia</button>')
    ativo_todas = "" if top else ' class="ativo"'
    chips.append(f'<button type="button"{ativo_todas} data-tag="">Todas ({total})</button>')
    cards = [_card(c, tags_cfg[c.tag].get("emoji", "🔥"), tags_cfg[c.tag].get("rotulo", c.tag), quando, True, cfg)
             for c in top]
    for tag in tags_cfg:
        lista = escolhidos.get(tag) or []
        if not lista:
            continue
        emoji = tags_cfg[tag].get("emoji", "🔥")
        rotulo = tags_cfg[tag].get("rotulo", tag)
        chips.append(f'<button type="button" data-tag="{_e(tag)}">{_e(emoji)} {_e(rotulo)} ({len(lista)})</button>')
        cards.extend(_card(c, emoji, rotulo, quando, False, cfg) for c in lista if id(c) not in ids_top)
    motivos = "".join(f"<li>{_e(m)}: {n}</li>" for m, n in recusados.most_common(20))
    vazio = "" if cards else "<p class='sub' style='padding:0 16px'>Nenhuma oferta passou nos filtros nesta rodada.</p>"
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Achadinhos do dia</title><style>{CSS}</style></head>
<body>
<header>
  <h1>Achadinhos <em>do dia</em></h1>
  <p class="sub">{_e(quando.strftime('%d/%m/%Y %H:%M'))} · {total} ofertas escolhidas de {_e(resumo.get('lidas', 0))} lidas ·
  histórico com {_e(resumo.get('produtos_no_banco', 0))} produtos</p>
</header>
<nav class="chips">{''.join(chips)}</nav>
{vazio}
<main>{''.join(cards)}</main>
<details><summary>Por que o resto ficou de fora</summary><ul>{motivos or '<li>nada recusado</li>'}</ul></details>
<footer>{_e(AVISO_FIM)} O selo verde (-X%) só aparece quando o nosso histórico confirma a queda;
"a confirmar" = ainda sem histórico suficiente, e a legenda não promete desconto.
Lembre de marcar "parceria paga" no Instagram.</footer>
<script>{JS}</script>
</body></html>"""


def achados(escolhidos: dict[str, list[Candidato]], cfg: dict, top: list[Candidato] | None = None) -> list[dict]:
    """Lista simples para a tela do dia a dia: um item por produto, ja com a mensagem pronta.
    Ordem: comprovados ('de/por') primeiro, pelos pontos; depois os ainda sem historico."""
    from .texto import mensagem, preco_de_por, tem_variacoes
    kw = _cfg_leg(cfg)
    ids_top = {id(c) for c in (top or [])}
    saida = []
    for tag, lista in escolhidos.items():
        tcfg = cfg["tags"].get(tag, {})
        emoji = tcfg.get("emoji", "🔥")
        for c in lista:
            o = c.oferta
            de, por, pct = preco_de_por(c)
            saida.append({
                "tag": tag, "rotulo": tcfg.get("rotulo", tag), "emoji": emoji,
                "nome": nome_curto(o.nome), "titulo": o.nome[:160], "loja": o.loja,
                "imagem": url_segura(o.imagem), "link": url_segura(c.link),
                "preco_de": de, "preco_por": por, "queda_pct": pct,
                # 30a rodada do Codex: variacao de preco e avisos de conferencia chegam a tela nova
                "variacoes": tem_variacoes(o), "preco_max": o.preco_max, "aviso": c.aviso or "",
                "link_conferido": bool(c.link_conferido),
                "comprovado": de is not None, "selo": c.selo, "relampago": bool(c.veredito.queda_brusca and de),
                "nota": o.nota, "vendas": o.vendas, "pontos": c.pontos, "top": id(c) in ids_top,
                "historico": c.veredito.rotulo,
                "mensagem": mensagem(c, emoji, "link", **kw), "mensagem_feed": mensagem(c, emoji, "feed", **kw),
            })
    saida.sort(key=lambda a: (not a["comprovado"], -a["pontos"]))
    return saida


def salvar_saidas(pasta: Path, escolhidos: dict[str, list[Candidato]], recusados: Counter,
                  cfg: dict, quando: datetime, resumo: dict, top: list[Candidato] | None = None) -> dict[str, Path]:
    tags_cfg = cfg["tags"]
    pasta.mkdir(parents=True, exist_ok=True)
    arquivos = {
        "vitrine": pasta / "vitrine.html",
        "csv": pasta / "ofertas.csv",
        "legendas": pasta / "legendas.txt",
        "legendas_feed": pasta / "legendas_feed.txt",
        "json": pasta / "ofertas.json",
        "achados": pasta / "achados.json",
        "mensagens": pasta / "mensagens.txt",
    }
    lista_achados = achados(escolhidos, cfg, top)
    arquivos["achados"].write_text(json.dumps({"quando": quando.isoformat(timespec="minutes"),
                                               "lidas": resumo.get("lidas", 0), "achados": lista_achados},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    arquivos["mensagens"].write_text(("\n\n" + "-" * 24 + "\n\n").join(a["mensagem"] for a in lista_achados) + "\n",
                                     encoding="utf-8")
    arquivos["vitrine"].write_text(gerar_html(escolhidos, recusados, cfg, quando, resumo, top), encoding="utf-8")

    linhas = []
    for tag in tags_cfg:
        for c in escolhidos.get(tag) or []:
            o, v = c.oferta, c.veredito
            linhas.append({
                "tag": tag, "produto": nome_curto(o.nome, 120), "loja": o.loja,
                "preco": f"{o.preco_min:.2f}".replace(".", ","),
                "desconto_shopee": o.desconto,
                "queda_real_pct": "" if v.queda_real is None else round(v.queda_real * 100),
                "preco_normal": "" if v.preco_normal is None else f"{v.preco_normal:.2f}".replace(".", ","),
                "veredito_preco": v.rotulo, "selo": c.selo, "nota": o.nota, "vendas": o.vendas,
                "comissao_pct": "" if o.comissao is None else round(o.comissao * 100, 1),
                "pontos": c.pontos, "reconferido": "sim" if c.reconferido else "não",
                "link_com_subid": "sim" if c.link_rastreado else "não",
                "aviso": c.aviso or "", "link": c.link, "item_id": o.item_id,
                "fim_periodo_api": "" if not o.periodo_fim else
                datetime.fromtimestamp(o.periodo_fim).strftime("%d/%m/%Y %H:%M"),
            })
    with arquivos["csv"].open("w", newline="", encoding="utf-8-sig") as f:  # abre certo no Excel
        campos = list(linhas[0]) if linhas else ["tag", "produto", "link"]
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows({k: celula_segura(val) for k, val in linha.items()} for linha in linhas)

    kw = _cfg_leg(cfg)
    for chave, canal in (("legendas", "link"), ("legendas_feed", "feed")):
        blocos = []
        for tag in tags_cfg:
            emoji = tags_cfg[tag].get("emoji", "🔥")
            blocos.extend(legenda(c, emoji, canal, **kw) for c in escolhidos.get(tag) or [])
        arquivos[chave].write_text(("\n\n" + "-" * 30 + "\n\n").join(blocos) + "\n", encoding="utf-8")
    arquivos["json"].write_text(json.dumps(linhas, ensure_ascii=False, indent=1), encoding="utf-8")
    return arquivos
