"""'Montar postagem': enquanto a Open API nao e liberada, a pessoa acha a promocao na Shopee, gera o
link no painel de afiliados (Link personalizado) e cola aqui o link e o preco que esta vendo.

O robo:
  1. confere o link na Shopee real com as MESMAS regras do 'Conferir links' - so monta a mensagem
     se o nivel for OK (endereco de produto + marcacao de afiliado posta pela Shopee);
  2. pega o nome que a Shopee pos no endereco (ou o nome digitado) e barra NBCAL, falsificacao e
     proibidos com os MESMOS bloqueios do nicho - os dois nomes passam pelo bloqueio;
  3. limpa o nome com o mesmo filtro da rodada (so palavras do vocabulario, nenhum numero ou
     promessa do vendedor);
  4. monta a mensagem no formato de sempre, so com "Por R$ Y": o "De R$ X" so existe quando o
     historico do robo comprova a queda (decisao do dono, 17/10), e aqui nao ha historico.
O preco e o que a pessoa digitou: a mensagem avisa que pode mudar, e a tela pede para conferir no app.
"""
from __future__ import annotations

import re

from .curadoria import verificar_atencao, verificar_bloqueio
from .links import examinar_link, nivel_do_exame, texto_do_exame
from .texto import nome_curto, reais

VERSAO_POSTAGEM = 1
MAX_POSTAGENS = 20
_TAM_NOME_DIGITADO = 150
_PRECO = re.compile(r"(?:R\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)(?:[,.]([0-9]{1,2}))?", re.ASCII)


def ler_preco(texto) -> float | None:
    """'29,90', 'R$ 29,90', '1.299,90', '29.90', '30' -> float. Qualquer outra coisa -> None.
    Faixa aceita: de R$ 0,50 a R$ 100.000,00."""
    t = str(texto or "").strip().replace(" ", " ")
    m = _PRECO.fullmatch(t)
    if not m:
        return None
    inteiro, centavos = m.group(1), m.group(2)  # '29.90': inteiro=29, centavos=90; '1.299': mil
    valor = int(inteiro.replace(".", "")) + (int(centavos.ljust(2, "0")) / 100 if centavos else 0)
    return round(valor, 2) if 0.5 <= valor <= 100_000 else None


def _tags_validas(cfg: dict) -> dict:
    return {k: v for k, v in (cfg.get("tags") or {}).items() if not k.startswith("_") and isinstance(v, dict)}


def montar_postagem(link: str, preco_texto: str, cfg: dict, nome_digitado: str = "",
                    tag: str = "maternidade", abrir=None) -> dict:
    """Resultado SEMPRE com 'ok' e 'motivos'. So ha 'mensagem' quando ok=True."""
    exame = examinar_link(link, abrir=abrir)
    preco = ler_preco(preco_texto)
    nome_digitado = " ".join(str(nome_digitado or "").split())  # INTEIRO: o bloqueio le tudo (44a rodada)
    tags = _tags_validas(cfg)
    tag = tag if tag in tags else "maternidade" if "maternidade" in tags else next(iter(tags), "")
    emoji = str(tags.get(tag, {}).get("emoji") or "🛍️")
    motivos: list[str] = []

    link_ok = nivel_do_exame(exame) == "ok"
    if not link_ok:
        motivos.append(f"Link: {texto_do_exame(exame)}")
    if preco is None:
        motivos.append("Preço: digite o preço que está na Shopee, por exemplo 29,90.")
    nome_endereco = exame.get("nome_inteiro") or exame.get("nome") or ""  # inteiro, nunca cortado
    if link_ok and not nome_endereco and not nome_digitado:
        motivos.append("Nome: o endereço do link não traz o nome do produto; digite o nome no campo Nome.")
    if len(nome_digitado) > _TAM_NOME_DIGITADO:  # recusa em vez de cortar: cortar esconderia o fim
        motivos.append(f"Nome: use no máximo {_TAM_NOME_DIGITADO} caracteres no nome digitado.")

    bloqueios = cfg.get("bloqueios") or {}
    combinados = cfg.get("bloqueios_combinados")
    for candidato in (nome_endereco, nome_digitado):  # os DOIS nomes passam pelo bloqueio
        if candidato:
            bloqueio = verificar_bloqueio(candidato, bloqueios, combinados)
            if bloqueio:
                motivos.append(f"Produto: {bloqueio}.")
                break
    avisos = [a for a in {verificar_atencao(n, cfg.get("atencao") or {}) for n in (nome_endereco, nome_digitado) if n} if a]

    base = nome_digitado or nome_endereco
    nome = nome_curto(base) if base else ""
    if base and nome == "Produto":  # o filtro do vocabulario nao deixou nada de pe
        motivos.append("Nome: depois de limpar promessas e números, não sobrou nome. Digite um nome simples, "
                       "por exemplo: Almofada de Amamentação.")
    resultado = {"versao": VERSAO_POSTAGEM, "link": link, "preco": preco, "tag": tag, "emoji": emoji,
                 "nome": nome, "nome_endereco": nome_endereco, "nome_digitado": nome_digitado,
                 "item": exame.get("item"), "afiliado": exame.get("afiliado") if nivel_do_exame(exame) == "ok" else None,
                 "conferencia": texto_do_exame(exame), "avisos": avisos, "motivos": motivos, "ok": not motivos}
    if motivos:
        return resultado
    corpo = ["#publi · link de afiliado", f"{emoji} {nome}", f"Por {reais(preco)}"]
    resultado["mensagem"] = "\n".join(corpo + [f"👉 {link}", "Preço pode mudar a qualquer momento."])
    resultado["mensagem_feed"] = "\n".join(corpo + ["🔗 Link nos stories", "Preço pode mudar a qualquer momento."])
    return resultado
