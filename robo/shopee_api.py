"""Cliente da API oficial de afiliados da Shopee Brasil (GraphQL).

Autenticacao (documentada pela Shopee e conferida em SDKs abertos):
    Authorization: SHA256 Credential={AppId}, Timestamp={ts}, Signature={sig}
    sig = sha256(AppId + ts + payload + Secret)   # payload = corpo JSON EXATO enviado

O segredo nunca vai para log, excecao ou arquivo de saida.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"

# Codigos de erro da Open API de afiliados -> explicacao para quem opera o robo.
ERROS = {
    10020: "autenticacao recusada: App ID/Secret errados, app desativado ou relogio "
           "do computador fora de hora (a assinatura leva a hora atual)",
    10030: "limite de chamadas da Shopee atingido (o robo espera e tenta de novo)",
    10031: "acesso negado pela Shopee",
    10032: "ID de afiliado invalido",
    10033: "conta de afiliado congelada",
    10034: "ID de afiliado bloqueado (lista negra)",
    10035: "a conta ainda nao tem acesso a Open API. Pedir a liberacao (gratis) no formulario "
           "https://help.shopee.com.br/portal/webform/bbce78695c364ba18c9cbceb74ec9091 e aguardar o e-mail",
    11000: "erro de negocio da Shopee",
    11001: "parametro invalido na consulta",
    11002: "erro de vinculo da conta de afiliado",
}
TEMPORARIOS = {10000, 10030}  # 10000 = "System Error" da Shopee
FATAIS_HTTP = {401, 403}

CAMPOS_OFERTA = (
    "itemId commissionRate sellerCommissionRate shopeeCommissionRate commission "
    "sales priceMax priceMin productCatIds ratingStar priceDiscountRate imageUrl "
    "productName shopId shopName shopType productLink offerLink "
    "periodStartTime periodEndTime"
)


class ErroShopee(Exception):
    def __init__(self, codigo: int | None, mensagem: str):
        self.codigo = codigo
        explicacao = ERROS.get(codigo or -1)
        texto = f"[{codigo}] {mensagem}" if codigo else mensagem
        if explicacao:
            texto += f" -> {explicacao}"
        super().__init__(texto)

    @property
    def temporario(self) -> bool:
        return self.codigo in TEMPORARIOS or self.codigo is None


def assinar(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    base = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _gql_str(valor: str) -> str:
    """Literal de string GraphQL seguro (JSON string e um literal GraphQL valido)."""
    return json.dumps(str(valor), ensure_ascii=False)


def _transporte_http(url: str, corpo: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=corpo, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:  # a Shopee manda o erro no corpo
        return e.code, e.read()


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _taxa(v) -> float | None:
    """Comissao chega como string; aceita fracao ("0.08") ou percentual ("8")."""
    n = _num(v)
    if n is None:
        return None
    return n / 100 if n > 1 else n


def _lista(v) -> list:
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


@dataclass
class Oferta:
    item_id: int
    shop_id: int | None
    nome: str
    loja: str
    preco_min: float
    preco_max: float
    desconto: int            # priceDiscountRate da Shopee, em pontos percentuais
    vendas: int
    nota: float | None
    comissao: float | None   # fracao (0.08 = 8%)
    imagem: str
    link_produto: str
    link_oferta: str
    cat_ids: list = field(default_factory=list)
    shop_type: list = field(default_factory=list)
    periodo_fim: int | None = None

    @property
    def preco_de_estimado(self) -> float | None:
        """'Preco de' implicito no desconto da Shopee (estimativa, pode arredondar)."""
        if not self.desconto or self.desconto <= 0 or self.desconto >= 100:
            return None
        return round(self.preco_min / (1 - self.desconto / 100), 2)

    @classmethod
    def de_no(cls, no: dict) -> "Oferta | None":
        """Um no estranho vira None (e e descartado) em vez de derrubar a pagina."""
        try:
            return cls._de_no(no)
        except (TypeError, ValueError, AttributeError, OverflowError):
            return None

    @classmethod
    def _de_no(cls, no: dict) -> "Oferta | None":
        if not isinstance(no, dict):
            return None
        preco_min = _num(no.get("priceMin"))
        item_id = no.get("itemId")
        if item_id is None or preco_min is None or preco_min <= 0:
            return None
        preco_max = _num(no.get("priceMax")) or preco_min
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            return None
        shop = _num(no.get("shopId"))
        fim = _num(no.get("periodEndTime"))
        return cls(
            item_id=item_id,
            shop_id=int(shop) if shop is not None else None,
            nome=(no.get("productName") or "").strip(),
            loja=(no.get("shopName") or "").strip(),
            preco_min=preco_min,
            preco_max=max(preco_max, preco_min),
            desconto=int(_num(no.get("priceDiscountRate")) or 0),
            vendas=int(_num(no.get("sales")) or 0),
            nota=_num(no.get("ratingStar")),
            comissao=_taxa(no.get("commissionRate")),
            imagem=no.get("imageUrl") or "",
            link_produto=no.get("productLink") or "",
            link_oferta=no.get("offerLink") or "",
            cat_ids=_lista(no.get("productCatIds")),
            shop_type=_lista(no.get("shopType")),
            periodo_fim=int(fim) if fim else None,
        )


class ClienteShopee:
    def __init__(self, app_id: str, secret: str, endpoint: str = ENDPOINT,
                 transporte: Callable | None = None, relogio: Callable = time.time,
                 dormir: Callable = time.sleep, intervalo: float = 1.0,
                 tentativas: int = 4, timeout: float = 30.0):
        if not app_id or not secret:
            raise ValueError("SHOPEE_APP_ID e SHOPEE_SECRET sao obrigatorios (arquivo .env)")
        self.app_id = str(app_id).strip()
        self._secret = str(secret).strip()
        self.endpoint = endpoint
        self._transporte = transporte or _transporte_http
        self._relogio = relogio
        self._dormir = dormir
        self.intervalo = intervalo
        self.tentativas = max(1, tentativas)
        self.timeout = timeout
        self._ultima = 0.0
        self.chamadas = 0

    def __repr__(self) -> str:  # nunca expor o segredo
        return f"ClienteShopee(app_id={self.app_id[:3]}***, endpoint={self.endpoint})"

    def _uma_chamada(self, query: str) -> dict:
        espera = self.intervalo - (self._relogio() - self._ultima)
        if espera > 0:
            self._dormir(espera)
        payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
        ts = int(self._relogio())
        assinatura = assinar(self.app_id, self._secret, ts, payload)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "RoboAchadinhos/1.0 (+python)",
            "Authorization": f"SHA256 Credential={self.app_id}, Timestamp={ts}, Signature={assinatura}",
        }
        self._ultima = self._relogio()
        self.chamadas += 1
        try:
            status, corpo = self._transporte(self.endpoint, payload.encode("utf-8"), headers, self.timeout)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            raise ErroShopee(None, self._sem_segredo(f"falha de rede: {e}")) from None
        try:
            dados = json.loads(corpo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            if status in FATAIS_HTTP:  # firewall/credencial: insistir nao adianta
                raise ErroShopee(10031, f"HTTP {status} sem JSON (bloqueio ou endpoint errado)") from None
            if status == 429 or status >= 500:
                raise ErroShopee(None, f"HTTP {status} sem JSON") from None
            raise ErroShopee(11000, f"resposta nao-JSON (HTTP {status})") from None
        erros = dados.get("errors") if isinstance(dados, dict) else None
        if erros:
            e0 = erros[0] if isinstance(erros, list) and erros else {}
            ext = e0.get("extensions") or {}
            codigo = ext.get("code")
            try:
                codigo = int(codigo) if codigo is not None else None
            except (TypeError, ValueError):
                codigo = None
            msg = self._sem_segredo(str(ext.get("message") or e0.get("message") or "erro sem mensagem"))
            if codigo is None:  # erro sem codigo da Shopee: o status HTTP decide
                if status in FATAIS_HTTP:
                    raise ErroShopee(10031, f"HTTP {status}: {msg}")
                if status == 429 or status >= 500:
                    raise ErroShopee(None, f"HTTP {status}: {msg}")
                codigo = 11001  # campo inexistente etc.: nao e temporario
            raise ErroShopee(codigo, msg)
        if status in FATAIS_HTTP:
            raise ErroShopee(10031, f"HTTP {status} (bloqueio ou credencial)")
        if status == 429 or status >= 500:
            raise ErroShopee(None, f"HTTP {status}")
        if status != 200 or not isinstance(dados, dict) or "data" not in dados:
            raise ErroShopee(11000, f"HTTP {status} sem dados")
        return dados["data"] or {}

    def _sem_segredo(self, texto: str) -> str:
        return texto.replace(self._secret, "***") if self._secret else texto

    def executar(self, query: str) -> dict:
        ultimo = None
        for tentativa in range(self.tentativas):
            try:
                return self._uma_chamada(query)
            except ErroShopee as e:
                if not e.temporario:
                    raise
                ultimo = e
                if tentativa + 1 < self.tentativas:
                    self._dormir(min(60, 2 ** (tentativa + 1)))
        raise ultimo  # type: ignore[misc]

    def buscar_ofertas(self, keyword: str | None = None, sort_type: int = 2, page: int = 1,
                       limit: int = 50, list_type: int | None = None,
                       match_id: int | None = None, cat_id: int | None = None,
                       item_id: int | None = None, shop_id: int | None = None,
                       campos: str = CAMPOS_OFERTA) -> tuple[list[Oferta], bool]:
        """productOfferV2. sortType: 1 relevancia, 2 mais vendidos, 3 maior preco,
        4 menor preco, 5 maior comissao. Retorna (ofertas, tem_proxima_pagina)."""
        args = [f"sortType: {int(sort_type)}", f"page: {int(page)}", f"limit: {int(limit)}"]
        if keyword:
            args.insert(0, f"keyword: {_gql_str(keyword)}")
        if list_type is not None:
            args.append(f"listType: {int(list_type)}")
        if match_id is not None:
            args.append(f"matchId: {int(match_id)}")
        if cat_id is not None:
            args.append(f"productCatId: {int(cat_id)}")
        if item_id is not None:
            args.append(f"itemId: {int(item_id)}")
        if shop_id is not None:
            args.append(f"shopId: {int(shop_id)}")
        query = ("query { productOfferV2(" + ", ".join(args) + ") { nodes { " + campos +
                 " } pageInfo { page limit hasNextPage } } }")
        dados = self.executar(query).get("productOfferV2") or {}
        ofertas = [o for o in (Oferta.de_no(n) for n in dados.get("nodes") or []) if o]
        tem_mais = bool((dados.get("pageInfo") or {}).get("hasNextPage"))
        return ofertas, tem_mais

    def link_curto(self, origin_url: str, sub_ids: list[str] | None = None) -> str:
        """generateShortLink: link rastreado de afiliado; subIds (ate 5) marcam a origem."""
        partes = [f"originUrl: {_gql_str(origin_url)}"]
        if sub_ids:
            partes.append("subIds: [" + ", ".join(_gql_str(s) for s in sub_ids[:5]) + "]")
        query = "mutation { generateShortLink(input: {" + ", ".join(partes) + "}) { shortLink } }"
        link = (self.executar(query).get("generateShortLink") or {}).get("shortLink")
        if not link:
            raise ErroShopee(11000, "generateShortLink voltou sem link")
        return link
