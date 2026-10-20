"""Confere se o link de afiliado ABRE o produto certo na Shopee, antes de ir para a tela.

Segue os redirecionamentos do link curto (s.shopee.com.br/...) ate a pagina final. O que vale e
a pagina onde a pessoa CHEGA (34a rodada do Codex), nao um endereco do meio do caminho:
  ok           - a pagina final abriu (2xx) e e a pagina de produto da Shopee com EXATAMENTE o ID
                 do item no caminho (/product/<loja>/<item> ou ...-i.<loja>.<item>): ganha o selo
  ok_sem_id    - abriu (2xx) na Shopee, mas a pagina final nao e a do produto (login, anti-robo,
                 inicio...): vai para a tela, SEM o selo
  quebrado     - 404/410, pagina de erro, pagina de OUTRO produto, saiu da Shopee, deixou o HTTPS,
                 porta estranha ou endereco malformado: o link NAO vai para a tela
  sem_resposta - a Shopee nao respondeu a tempo (403/429/5xx, rede, prazo total): vai, SEM o selo

Todo endereco avaliado (o link inicial e cada salto) tem de ser o MESMO para o robo e para o
navegador: ASCII visivel, sem barra invertida (35a rodada: no navegador '\\' vira '/'), na forma
absoluta limpa https://host[:443]/... ou, no redirecionamento, caminho com uma barra so no comeco
(36a rodada: '///product/...' o Python junta no host atual e o navegador le o host 'product').
Qualquer outra forma = quebrado.

Teste REAL de 19/10/2026: link curto inexistente NAO da 404 - vai (301) para
https://shope.ee/error_page, que responde 200; e QUALQUER pagina de produto responde 200 a um robo
(e um app de pagina unica), ate a de um produto que nao existe. Por isso o selo afirma so que o link
leva a pagina do produto certo; que o produto existe quem garante e a API, consultada na mesma rodada.
"""
from __future__ import annotations

import http.cookiejar
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import parse_qs, quote_from_bytes, unquote, urljoin, urlsplit

HOSTS_SHOPEE = ("shopee.com.br", "shope.ee", "shp.ee")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
_REDIRECIONA = (301, 302, 303, 307, 308)
# so os caminhos de erro de verdade da Shopee (33a rodada: "Terror-Livro-i.55.9" nao e erro)
_CAMINHO_ERRO = re.compile(r"^/(?:error_page|error|404|not-found|notfound)(?:/|$)", re.IGNORECASE)
# ID da Shopee: so digitos ASCII, sem zero a esquerda, ate 20 (34a rodada: '²' e 4.301 digitos
# derrubavam o int()). O caminho INTEIRO tem de ser a pagina do produto.
_ID = r"([1-9][0-9]{0,19})"
# nome do produto no endereco: caracteres comuns de caminho e %XX, menos %2F ('/'), %5C ('\') e %00
# (um servidor que decodificasse esses formaria outro caminho)
_NOME = r"(?:[A-Za-z0-9\-._~!$&'()*+,;=:@]|%(?!2[Ff]|5[Cc]|00)[0-9A-Fa-f]{2})+"
_PAGINA_PRODUTO = (re.compile(rf"/(?:universal-link/)?product/{_ID}/{_ID}/?", re.ASCII),
                   re.compile(rf"/{_NOME}-i\.{_ID}\.{_ID}/?", re.ASCII))
_NOME_NO_CAMINHO = re.compile(rf"/({_NOME})-i\.{_ID}\.{_ID}/?", re.ASCII)
_SEGURO_NA_URL = b":/?#[]@!$&'()*+,;=%-._~"
# marcacao que a Shopee poe no link de afiliado (medido em 19/10 num link curto real):
# utm_medium=affiliates e utm_source=an_<ID do afiliado>
_ID_AFILIADO = re.compile(r"an_[0-9]{1,20}", re.ASCII)
# Forma absoluta que o Python e o navegador leem IGUAL (36a rodada: '///product/..' o Python junta
# no host atual e o navegador le o host 'product'): https:// + host simples + :443 opcional, e logo
# depois / ? # ou fim. Usuario, porta, '%', barra a mais = fora.
_ROTULO = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_ABSOLUTA = re.compile(rf"https://{_ROTULO}(?:\.{_ROTULO})*(?::443)?(?=[/?#]|$)", re.ASCII | re.IGNORECASE)
_PONTO = re.compile(r"%2e", re.IGNORECASE)


def _partes(url: str):
    """urlsplit que nunca derruba a rodada (33a rodada: 'https://[shopee.com.br/x')."""
    try:
        p = urlsplit(url or "")
        _ = p.port  # porta invalida levanta ValueError aqui
        return p
    except ValueError:
        return None


def _ascii_visivel(url: str) -> bool:
    """So ASCII visivel e sem barra invertida: o navegador e o robo leem o MESMO endereco."""
    return bool(url) and all(0x21 <= ord(ch) <= 0x7E and ch != "\\" for ch in url)


def host_shopee(url: str) -> bool:
    p = _partes(url)
    h = ((p.hostname if p else "") or "").lower()
    return any(h == x or h.endswith("." + x) for x in HOSTS_SHOPEE)


def _tem_ponto(caminho: str) -> bool:
    """Segmento '.' ou '..' (tambem %2e): cada leitor resolve de um jeito, entao nao aceitamos."""
    return any(_PONTO.sub(".", seg) in (".", "..") for seg in (caminho or "").split("/"))


def endereco_seguro(url: str) -> bool:
    """ASCII visivel, forma absoluta limpa (https://host[:443]), host da Shopee, sem usuario/senha
    e sem '.'/'..' no caminho: o mesmo endereco para o robo e para o navegador."""
    p = _partes(url)
    return _ascii_visivel(url) and bool(_ABSOLUTA.match(url)) and bool(p) and p.scheme == "https" \
        and host_shopee(url) and p.port in (None, 443) and p.username is None and p.password is None \
        and not _tem_ponto(p.path)


def pagina_de_erro(url: str) -> bool:
    p = _partes(url)
    return bool(p) and bool(_CAMINHO_ERRO.match(p.path or "/"))


def produto_da_pagina(url: str) -> tuple[int, int] | None:
    """(loja, item) EXATOS quando o endereco E a pagina de um produto da Shopee: /product/<loja>/<item>
    ou /<nome>-i.<loja>.<item>. Parametro ?itemid= nao conta (34a rodada: /buyer/login?itemid=...)."""
    if not _ascii_visivel(url):
        return None
    p = _partes(url)
    if not p:
        return None
    for padrao in _PAGINA_PRODUTO:
        m = padrao.fullmatch(p.path or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def item_da_pagina(url: str) -> int | None:
    """So o ID do item da pagina de produto (ver produto_da_pagina)."""
    produto = produto_da_pagina(url)
    return produto[1] if produto else None


def nome_da_pagina(url: str) -> str | None:
    """O nome do produto que a Shopee poe no endereco (/Nome-Do-Produto-i.<loja>.<item>), legivel.
    So para a pessoa reconhecer o produto na conferencia: nao vai para mensagem nenhuma."""
    p = _partes(url) if _ascii_visivel(url) else None
    m = _NOME_NO_CAMINHO.fullmatch(p.path or "") if p else None
    if not m:
        return None
    nome = unquote(m.group(1), errors="replace").replace("-", " ")
    nome = " ".join("".join(ch if ch.isprintable() else " " for ch in nome).split())
    return nome[:90] or None


def _id_esperado(item_id) -> int | None:
    """O ID do item que o card mostra; qualquer coisa estranha vira None (= nunca ganha o selo)."""
    if isinstance(item_id, bool):
        return None
    if isinstance(item_id, int):
        return item_id if 0 < item_id < 10 ** 20 else None
    if isinstance(item_id, str) and re.fullmatch(_ID, item_id, re.ASCII):
        return int(item_id)
    return None


def _destino(location: str) -> str | None:
    """Location do jeito que um navegador usaria: bytes nao-ASCII viram %XX (nome de produto com
    acento). A checagem e nos BYTES (35a rodada: o UTF-8 de 'à' tem o byte A0, que lido em latin-1
    parece espaco): espaco, controle e barra invertida ASCII = malformado."""
    if not location:
        return None
    try:
        bruto = location.encode("latin-1")  # o http.client decodifica o cabecalho em latin-1
    except UnicodeEncodeError:
        bruto = location.encode("utf-8")
    if any(b <= 0x20 or b == 0x7F or b == 0x5C for b in bruto):
        return None
    return quote_from_bytes(bruto, safe=_SEGURO_NA_URL)


def _resolver(base: str, location: str) -> str | None:
    """Proximo endereco SO nas duas formas que o Python e o navegador resolvem igual: absoluta
    limpa (https://...) ou caminho com UMA barra no comeco (/...). '//host', '///x', 'https:x',
    caminho sem barra, so '?x' ou '#x' = None (36a rodada)."""
    destino = _destino(location)
    if not destino:
        return None
    if destino[:8].lower() == "https://":
        proximo = destino
    elif destino.startswith("/") and not destino.startswith("//"):
        if _tem_ponto(re.split(r"[?#]", destino, maxsplit=1)[0]):
            return None
        try:
            proximo = urljoin(base, destino)
        except ValueError:
            return None
    else:
        return None
    return proximo if endereco_seguro(proximo) else None


def _curto(url: str) -> str:
    """host + caminho, sem a consulta (nao espalha parametros de rastreio no log)."""
    p = _partes(url)
    return f"{p.hostname}{p.path}" if p and p.hostname else "(endereco invalido)"


class _NaoSeguir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kw):  # devolve o 3xx para quem chamou
        return None


def _abridor_http() -> Callable[[str, float], tuple[int, str | None]]:
    """Um 'navegador' por link: guarda os cookies entre os saltos, nao segue sozinho, nao baixa a pagina."""
    opener = urllib.request.build_opener(_NaoSeguir, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def abrir(url: str, timeout: float) -> tuple[int, str | None]:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "pt-BR"}, method="GET")
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, r.headers.get("Location")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location")
    return abrir


def conferir_link(url: str, item_id: int | None = None, abrir: Callable | None = None,
                  max_saltos: int = 8, timeout: float = 10.0, prazo_total: float = 30.0,
                  relogio: Callable[[], float] = time.monotonic, trilha: list | None = None,
                  enderecos: list | None = None) -> tuple[str, str]:
    """(estado, detalhe). Ver os estados no topo do arquivo. NUNCA levanta excecao (34a rodada):
    defeito aqui tira o selo, mas nao derruba a rodada. `trilha` (opcional) recebe cada salto como
    "status host/caminho"; `enderecos` (opcional) recebe cada endereco ABERTO, completo, em ordem
    (o ultimo e a pagina final quando o estado e ok/ok_sem_id).
    O prazo aqui e suave (cada salto usa o que sobra); o duro e o de conferir_com_prazo."""
    try:
        return _conferir(url, _id_esperado(item_id), abrir or _abridor_http(), max_saltos, timeout,
                         prazo_total, relogio, trilha if trilha is not None else [],
                         enderecos if enderecos is not None else [])
    except Exception as e:  # noqa: BLE001
        return "sem_resposta", f"falha ao conferir: {type(e).__name__}"


def _conferir(url, esperado, abrir, max_saltos, timeout, prazo_total, relogio, trilha,
              enderecos) -> tuple[str, str]:
    if not endereco_seguro(url):  # o link inicial passa pelas MESMAS regras dos saltos (35a rodada)
        return "quebrado", "link fora da Shopee ou endereco invalido"
    fim = relogio() + prazo_total
    atual = url
    for _ in range(max_saltos):
        restante = fim - relogio()
        if restante <= 0:
            return "sem_resposta", f"a Shopee nao respondeu em {prazo_total:.0f}s"
        try:
            status, location = abrir(atual, min(timeout, restante))
        except Exception as e:  # noqa: BLE001 - rede, TLS, timeout: nada disso derruba a rodada
            return "sem_resposta", f"sem resposta: {type(e).__name__}"
        trilha.append(f"{status} {_curto(atual)}")
        enderecos.append(atual)
        if status in _REDIRECIONA:
            if not location:
                return "quebrado", f"HTTP {status} sem destino"
            proximo = _resolver(atual, location)
            if not proximo:
                return "quebrado", "redireciona para fora da Shopee, sem HTTPS ou endereco malformado"
            if pagina_de_erro(proximo):
                return "quebrado", f"a Shopee mandou para a pagina de erro ({_curto(proximo)})"
            atual = proximo
            continue  # segue ate o destino final: o selo so vem se ele ABRIR (33a rodada)
        if 200 <= status < 300:
            if pagina_de_erro(atual):
                return "quebrado", f"pagina de erro da Shopee ({_curto(atual)})"
            item = item_da_pagina(atual)
            if item is not None and esperado is not None and item != esperado:
                return "quebrado", f"o link abre OUTRO produto (ID {item})"
            if item is not None and item == esperado:
                return "ok", _curto(atual)
            return "ok_sem_id", _curto(atual)
        if status in (404, 410):
            return "quebrado", f"HTTP {status}"
        return "sem_resposta", f"HTTP {status}"
    return "sem_resposta", "redirecionamentos demais"


def conferir_com_prazo(url: str, item_id: int | None = None, prazo_total: float = 30.0, folga: float = 2.0,
                       abrir: Callable | None = None, trilha: list | None = None,
                       enderecos: list | None = None) -> tuple[str, str]:
    """conferir_link com prazo DURO (34a/35a rodadas): corre numa linha separada e, se passar do
    prazo, devolve sem_resposta e quem chamou segue (a linha presa morre sozinha no timeout)."""
    caixa: list = []
    saltos: list = []
    abertos: list = []
    linha = threading.Thread(
        target=lambda: caixa.append(conferir_link(url, item_id, abrir=abrir, prazo_total=prazo_total,
                                                  trilha=saltos, enderecos=abertos)),
        daemon=True)
    linha.start()
    linha.join(prazo_total + folga)
    if trilha is not None:
        trilha.extend(list(saltos))
    if enderecos is not None:
        enderecos.extend(list(abertos))
    return caixa[0] if caixa else ("sem_resposta", f"a Shopee nao respondeu em {prazo_total:.0f}s")


def verificador_com_pausa(pausa: float = 0.4, prazo_total: float = 30.0, folga: float = 2.0,
                          abrir: Callable | None = None, desistir_apos: int = 3) -> Callable[[str, int | None], tuple[str, str]]:
    """O verificador da rodada real: prazo duro por link e pausa curta entre links, para nao parecer
    robo. Se a Shopee deixar de responder `desistir_apos` vezes seguidas (bloqueio, limite, fora do
    ar), para de conferir NESTA rodada: os links seguintes vao sem o selo, e a rodada termina no
    tempo em vez de esperar 30 s por link."""
    seguidos = [0]

    def verificar(url: str, item_id: int | None = None) -> tuple[str, str]:
        if seguidos[0] >= desistir_apos:
            return "sem_resposta", "conferencia pausada nesta rodada: a Shopee parou de responder"
        resultado = conferir_com_prazo(url, item_id, prazo_total=prazo_total, folga=folga, abrir=abrir)
        seguidos[0] = seguidos[0] + 1 if resultado[0] == "sem_resposta" else 0
        time.sleep(pausa)
        return resultado
    return verificar


# ---------------------------------------------------------------------------------------------
# "Conferir links": links colados a mao (gerados no painel de afiliados, sem a Open API).
# Sem saber qual produto e o certo, o robo diz para ONDE a Shopee leva o link, o que esta escrito
# no endereco final (IDs e nome) e se ELA pos a marcacao de afiliado - sem API e sem .env. Que o
# produto existe, so abrindo (qualquer endereco de produto responde 200 a um robo).
# ---------------------------------------------------------------------------------------------
MAX_LINKS_COLADOS = 20
# versao do saida/conferencia.json: a tela so mostra resultado da versao ATUAL (40a rodada: um
# resultado salvo pela versao anterior, sem os campos novos, ganhava o OK)
VERSAO_CONFERENCIA = 2
_TAM_MAX_LINK = 600
_PONTUACAO_FIM = ".,;:!?)]}>\"'»”’"
_PONTUACAO_INICIO = "([{<\"'«“‘"
ESTADOS_EXAME = ("produto", "outra_pagina", "quebrado", "sem_resposta")
ICONES = {"ok": "✓", "aviso": "⚠", "erro": "✗", "espera": "…"}
# os motivos mais comuns, em frase de gente (o resto aparece como veio)
_MOTIVOS = (("link fora da Shopee ou endereco invalido", "não é um link da Shopee, ou o endereço está incompleto"),
            ("a Shopee mandou para a pagina de erro", "a Shopee mandou para a página de erro (link inexistente ou expirado)"),
            ("pagina de erro da Shopee", "a Shopee mostrou a página de erro (link inexistente ou expirado)"),
            ("HTTP 404", "a página não existe mais (HTTP 404)"), ("HTTP 410", "a página não existe mais (HTTP 410)"),
            ("redireciona para fora da Shopee", "o link leva para fora da Shopee ou para um endereço estranho"))


def links_do_texto(texto: str, limite: int = MAX_LINKS_COLADOS) -> list[str]:
    """Os links de um texto colado (mensagem, lista, planilha): um por palavra, sem a pontuacao em
    volta, sem repetir, no maximo `limite`. Link da Shopee sem https:// ganha o https://."""
    vistos: list[str] = []
    for palavra in (texto or "").split():
        palavra = palavra.lstrip(_PONTUACAO_INICIO).rstrip(_PONTUACAO_FIM)
        minuscula = palavra.lower()
        if minuscula.startswith("http://") and host_shopee(palavra):
            palavra = "https://" + palavra[7:]
        elif not minuscula.startswith(("https://", "http://")):
            if not any(minuscula.startswith(h + "/") or minuscula.startswith("s." + h + "/")
                       for h in HOSTS_SHOPEE):
                continue
            palavra = "https://" + palavra
        if len(palavra) > _TAM_MAX_LINK or palavra in vistos:
            continue
        vistos.append(palavra)
        if len(vistos) >= limite:
            break
    return vistos


def marca_de_afiliado(enderecos: list[str]) -> str | None:
    """A marcacao de afiliado no caminho do link: o ID 'an_...' quando ha utm_medium=affiliates e
    utm_source=an_<ID>; 'sim' quando ha so utm_medium=affiliates; None quando nao ha marcacao."""
    achou = None
    for endereco in enderecos:
        p = _partes(endereco)
        if not p:
            continue
        consulta = parse_qs(p.query or "", keep_blank_values=True)
        if not any(v.strip().lower() == "affiliates" for v in consulta.get("utm_medium", [])):
            continue
        fonte = next((v for v in consulta.get("utm_source", []) if _ID_AFILIADO.fullmatch(v)), None)
        if fonte:
            return fonte
        achou = "sim"
    return achou


def examinar_link(url: str, abrir: Callable | None = None, prazo_total: float = 30.0,
                  folga: float = 2.0) -> dict:
    """Confere UM link colado: para onde a Shopee o leva, se o endereco final e o de uma pagina de
    produto (e quais IDs/nome estao NELE) e se a Shopee pos a marcacao de afiliado no caminho.
    Usa as mesmas regras e o mesmo prazo duro da rodada. Nunca levanta excecao.

    O que NAO da para saber sem a API (39a rodada): se o produto existe e se o nome e o dele -
    qualquer endereco de produto responde 200 a um robo. Por isso:
    - `afiliado` so conta a marcacao que apareceu DEPOIS de um redirecionamento da Shopee e que nao
      veio escrita no link colado (`marca_escrita` = a pessoa ja colou com utm_medium=affiliates);
    - `loja`/`item`/`nome` sao o que esta escrito no endereco final, nada alem disso."""
    trilha: list = []
    enderecos: list = []
    estado, detalhe = conferir_com_prazo(url, None, prazo_total=prazo_total, folga=folga, abrir=abrir,
                                         trilha=trilha, enderecos=enderecos)
    # sem item esperado, uma pagina que abriu (2xx) sempre volta como ok_sem_id
    final = enderecos[-1] if estado == "ok_sem_id" and enderecos else None
    produto = produto_da_pagina(final) if final else None
    if estado == "quebrado":
        situacao = "quebrado"
    elif estado != "ok_sem_id" or not final:
        situacao = "sem_resposta"
    else:
        situacao = "produto" if produto else "outra_pagina"
    marca_colada = marca_de_afiliado([url])
    return {"link": url, "estado": situacao, "detalhe": detalhe, "trilha": trilha,
            "destino": _curto(final) if final else None,
            "redirecionou": len(enderecos) > 1,
            "loja": produto[0] if produto else None, "item": produto[1] if produto else None,
            "nome": nome_da_pagina(final) if produto else None,
            "afiliado": marca_de_afiliado(enderecos[1:]) if final and marca_colada is None else None,
            "marca_escrita": marca_colada is not None}


def _marcacao_da_shopee(r: dict) -> str | None:
    """O ID an_<digitos> que a SHOPEE pos, com TODAS as provas explicitas (40a/41a rodadas: campo
    ausente nunca conta a favor): ela redirecionou, o link colado nao trazia marcacao escrita e o ID
    e valido. Qualquer frase que diga "a Shopee pos a marcacao" passa por aqui."""
    afiliado = r.get("afiliado")
    if (r.get("redirecionou") is True and r.get("marca_escrita") is False and isinstance(afiliado, str)
            and _ID_AFILIADO.fullmatch(afiliado)):
        return afiliado
    return None


def _so_utm_medium(r: dict) -> bool:
    """A Shopee pos utm_medium=affiliates, mas SEM o ID an_<digitos>: vale dizer so isso."""
    return r.get("afiliado") == "sim" and r.get("redirecionou") is True and r.get("marca_escrita") is False


def _prova_de_afiliado(r: dict) -> bool:
    """O OK: endereco de produto + marcacao da Shopee com ID valido (_marcacao_da_shopee)."""
    return r.get("estado") == "produto" and _marcacao_da_shopee(r) is not None


def nivel_do_exame(r: dict) -> str:
    """ok = a Shopee levou o link ao endereco de um produto E pos a marcacao de afiliado com o ID
    (todas as provas de _prova_de_afiliado); aviso = abriu, mas falta algo; erro = nao abre;
    espera = a Shopee nao respondeu. Nenhum nivel afirma que o produto existe (sem a API, nao da)."""
    estado = r.get("estado")
    if estado == "produto":
        return "ok" if _prova_de_afiliado(r) else "aviso"
    if estado == "outra_pagina":
        return "aviso"
    return "erro" if estado == "quebrado" else "espera"


def _motivo_legivel(detalhe) -> str:
    detalhe = str(detalhe or "")
    for comeco, frase in _MOTIVOS:
        if detalhe.startswith(comeco):
            return frase
    return detalhe


def texto_do_exame(r: dict) -> str:
    """A frase que a pessoa le para cada link conferido. So afirma o que foi medido: para onde a
    Shopee levou o link, o que esta escrito no endereco e a marcacao que ELA pos (39a rodada)."""
    if r.get("estado") == "produto":
        nome = f", nome no endereço: “{r.get('nome')}”" if r.get("nome") else ""
        endereco = f"endereço do produto {r.get('item')} (loja {r.get('loja')}{nome})"
        conferir = " Toque em Abrir para ver se é o produto certo e se está à venda."
        if _prova_de_afiliado(r):  # a unica frase de sucesso: so com TODAS as provas (40a rodada)
            return (f"A Shopee leva este link ao {endereco} e põe a marcação de afiliado "
                    f"{_marcacao_da_shopee(r)}.{conferir}")
        if r.get("marca_escrita") is True:
            return (f"É o {endereco} com a marcação de afiliado escrita no próprio link colado: a Shopee "
                    "não pôs nem confirmou nada. Use o link curto gerado em Link personalizado.")
        if _so_utm_medium(r):
            return (f"A Shopee leva este link ao {endereco} com utm_medium=affiliates, mas sem o ID de "
                    "afiliado (an_…) no endereço. Confira em Abrir e no painel de afiliados.")
        if r.get("afiliado"):
            return f"Leva ao {endereco}, mas não deu para confirmar a marcação de afiliado. Confira este link de novo."
        return (f"Leva ao {endereco}, mas a Shopee não pôs a marcação de afiliado no caminho. Se você colou "
                "o link direto do produto, ele não é link de afiliado: gere o link em Link personalizado.")
    if r.get("estado") == "outra_pagina":
        # 41a rodada: a frase "a Shopee pos a marcacao" tambem aqui so com o ID valido
        if _marcacao_da_shopee(r):
            marca = f" A Shopee pôs a marcação de afiliado {_marcacao_da_shopee(r)}."
        elif _so_utm_medium(r):
            marca = " Tem utm_medium=affiliates, mas sem o ID de afiliado (an_…)."
        else:
            marca = ""
        return f"Abre na Shopee, mas não num endereço de produto (chegou em {r.get('destino')}).{marca}"
    if r.get("estado") == "quebrado":
        return f"Não abre: {_motivo_legivel(r.get('detalhe'))}."
    return f"A Shopee não respondeu agora ({r.get('detalhe')}). Tente de novo em alguns minutos."
