"""Curadoria: decide o que merece ir para o perfil.

Ordem de corte (a primeira que falhar e o motivo registrado):
  bloqueio legal/falsificacao -> fora do nicho -> honestidade do preco ->
  desconto (real se ha historico) -> nota -> vendas -> faixa de preco -> comissao -> sem link
Quem passa recebe pontos (uso interno, so para ordenar) e disputa a vaga da tag.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

from .precos import Veredito
from .shopee_api import Oferta

STOP = {"de", "da", "do", "das", "dos", "e", "com", "para", "p", "kit", "c", "em", "a", "o",
        "un", "unidade", "pc", "peca", "novo", "nova", "promocao", "oferta", "envio",
        "imediato", "frete", "grati", "gratis", "original"}

NOMES_BLOQUEIO = {
    "nbcal": "bloqueado: NBCAL (Decreto 9.579/2018 proíbe promover mamadeira, bico, chupeta e fórmula/leite infantil)",
    "falsificacao": "bloqueado: indício de falsificação",
    "proibidos": "bloqueado: produto proibido ou de venda controlada",
}
NOMES_ATENCAO = {
    "inmetro": "conferir selo do Inmetro antes de divulgar",
    "anvisa": "conferir registro/notificação na Anvisa antes de divulgar",
    "anatel": "conferir homologação da Anatel antes de divulgar",
    "sono_seguro": "item desaconselhado por recomendações de sono seguro do bebê (SBP)",
    "kit": "conferir se o kit traz mamadeira, bico ou chupeta (NBCAL)",
}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _singular(p: str) -> str:
    """Plural -> singular aproximado (panelas->panela, colchoes->colchao, luzes->luz)."""
    if len(p) <= 3:
        return p
    if p.endswith(("oes", "aes")):
        return p[:-3] + "ao"
    if p.endswith(("res", "zes", "ses")) and len(p) > 4:
        return p[:-2]
    if p.endswith("s") and not p.endswith(("is", "us")):
        return p[:-1]
    return p


def raiz(texto: str) -> str:
    """Texto normalizado e no singular: a base de toda comparacao de palavras."""
    return " ".join(_singular(p) for p in normalizar(texto).split())


def _tem(norm_raiz: str, frase: str) -> bool:
    f = raiz(frase)
    return bool(f) and f" {f} " in f" {norm_raiz} "


def tokens(texto: str) -> set[str]:
    return {t for t in raiz(texto).split() if t not in STOP and len(t) > 1}


def similaridade(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_LETRA_NUMERO = re.compile(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])")
_MIN_GRUDADO = 6  # termos curtos ('arma', 'vape', 'chuca') so como palavra inteira: 'armario', 'machucado'


def _raiz_bloqueio(nome: str) -> str:
    """raiz() com letra e numero separados (45a rodada: 'Mamadeira260ml' escapava do bloqueio)."""
    return raiz(_LETRA_NUMERO.sub(" ", normalizar(nome)))


def _tem_bloqueio(norm: str, compacto: str, frase: str) -> bool:
    """Palavra inteira OU grudada: 'kitmamadeira', 'MamadeiraAnticolica'. Bloquear a mais e seguro
    (o produto so fica de fora); deixar passar NBCAL nao e."""
    if _tem(norm, frase):
        return True
    alvo = raiz(frase).replace(" ", "")
    return len(alvo) >= _MIN_GRUDADO and alvo in compacto


def verificar_bloqueio(nome: str, bloqueios: dict, combinados: dict | None = None) -> str | None:
    norm = _raiz_bloqueio(nome)
    compacto = normalizar(nome).replace(" ", "")
    for grupo, lista in bloqueios.items():
        if grupo.startswith("_"):
            continue
        if any(_tem_bloqueio(norm, compacto, p) for p in lista):
            return NOMES_BLOQUEIO.get(grupo, f"bloqueado: {grupo}")
    for grupo, regras in (combinados or {}).items():
        if grupo.startswith("_"):
            continue
        for regra in regras:
            if _tem(norm, regra["palavra"]) and any(_tem(norm, c) for c in regra["com"]):
                return NOMES_BLOQUEIO.get(grupo, f"bloqueado: {grupo}")
    return None


def verificar_atencao(nome: str, atencao: dict) -> str | None:
    norm = _raiz_bloqueio(nome)
    avisos = [NOMES_ATENCAO.get(g, f"atenção: {g}") for g, lista in atencao.items()
              if not g.startswith("_") and any(_tem(norm, p) for p in lista)]
    return "; ".join(avisos) or None


def classificar(nome: str, tags: dict, origens: set[str] | None = None,
                excluir_global: list[str] | None = None) -> tuple[str | None, str]:
    """Retorna (tag, confianca). Exige ao menos UMA palavra da tag no titulo: ter vindo
    da busca da tag nao basta (busca da Shopee devolve muito produto fora do nicho).
    A busca de origem so desempata."""
    norm = raiz(nome)
    if any(_tem(norm, p) for p in excluir_global or []):
        return None, "nenhuma"
    origens = origens or set()
    melhor, melhor_pts, melhor_hits = None, 0.0, 0
    for tag, cfg in tags.items():
        if any(_tem(norm, p) for p in cfg.get("excluir", [])):
            continue
        hits = [p for p in cfg.get("palavras", []) if _tem(norm, p)]
        if not hits:
            continue
        # peso: tag de nicho especifico (maternidade, bebe) vence a generica (casa)
        pts = sum(len(raiz(p).split()) for p in hits) * float(cfg.get("peso", 1.0))
        pts += 0.1 if tag in origens else 0
        if pts > melhor_pts:
            melhor, melhor_pts, melhor_hits = tag, pts, len(hits)
    if melhor is None:
        return None, "nenhuma"
    return melhor, "alta" if melhor_hits >= 2 else "média"


@dataclass
class Candidato:
    oferta: Oferta
    veredito: Veredito
    tag: str | None = None
    confianca: str = "nenhuma"
    recusa: str | None = None
    aviso: str | None = None
    pontos: float = 0.0
    link: str = ""
    link_rastreado: bool = False
    selo: str = ""            # NOVO | BAIXOU DE NOVO
    reconferido: bool = False
    link_conferido: bool = False  # o link abriu o produto certo na Shopee (robo.links)
    origens: set = field(default_factory=set)

    @property
    def aprovado(self) -> bool:
        return self.recusa is None


def comissao_reais(o: Oferta) -> float | None:
    return None if o.comissao is None else o.preco_min * o.comissao


def pontuar(o: Oferta, v: Veredito, shop_types_bonus: list | None = None) -> float:
    """0-100, so para ordenar. A queda REAL pesa muito mais que o % anunciado,
    e produto sem historico nao ganha nada por desconto que ninguem confirmou."""
    s = min(o.desconto, 80) / 80 * 5
    if v.queda_real is not None:
        s += max(0.0, min(v.queda_real, 0.5)) / 0.5 * 35
    if o.nota is not None:
        s += max(0.0, min((o.nota - 4.5) / 0.5, 1.0)) * 15
    s += min(math.log10(o.vendas + 1) / 4, 1.0) * 15
    cr = comissao_reais(o)
    if cr is not None:
        s += min(cr / 5.0, 1.0) * 15  # R$ 5 por venda ja e o teto
    if shop_types_bonus and set(o.shop_type) & set(shop_types_bonus):
        s += 5
    if v.status == "menor_preco":
        s += 5
    if v.queda_brusca:
        s += 5
    return round(min(s, 100.0), 2)


def avaliar_candidato(o: Oferta, v: Veredito, cfg: dict, origens: set[str] | None = None) -> Candidato:
    f = cfg["filtros"]
    c = Candidato(oferta=o, veredito=v, origens=set(origens or ()))
    c.tag, c.confianca = classificar(o.nome, cfg["tags"], c.origens, cfg.get("excluir_global"))
    c.aviso = verificar_atencao(o.nome, cfg.get("atencao", {}))

    min_real = f.get("desconto_minimo_real", f["desconto_minimo"])
    if v.queda_real is not None:  # com historico, vale a queda que NOS vimos
        desconto_ok = v.queda_real * 100 >= min_real
        msg_desconto = f"queda real abaixo de {min_real}%"
    else:
        desconto_ok = o.desconto >= f["desconto_minimo"]
        msg_desconto = f"desconto abaixo de {f['desconto_minimo']}%"
    com_min = f.get("comissao_minima", 0)

    c.recusa = (
        verificar_bloqueio(o.nome, cfg.get("bloqueios", {}), cfg.get("bloqueios_combinados"))
        or (None if c.tag else "fora do nicho")
        or (None if v.aceito else v.rotulo)
        or (None if desconto_ok else msg_desconto)
        or (None if o.nota is not None and o.nota >= f["nota_minima"]
            else f"nota abaixo de {f['nota_minima']} (ou sem nota)")
        or (None if o.vendas >= f["vendas_minimas"] else f"menos de {f['vendas_minimas']} vendas")
        or (None if f["preco_minimo"] <= o.preco_min <= f["preco_maximo"] else "fora da faixa de preço")
        or (None if o.comissao is None or o.comissao >= com_min
            else f"comissão abaixo de {round(com_min * 100)}%")
        or (None if (o.link_produto or o.link_oferta) else "sem link")
    )
    if c.aprovado:
        c.pontos = pontuar(o, v, f.get("shop_types_bonus"))
    return c


def filas_por_tag(candidatos: list[Candidato]) -> dict[str, list[Candidato]]:
    """Todos os aprovados de cada tag, em ordem de pontos. Os limites (loja, repetido,
    sem historico) NAO cortam aqui: valem contra o que ja foi ACEITO na hora de preencher,
    para a reserva nao sumir antes da reconferencia."""
    filas: dict[str, list[Candidato]] = {}
    for c in sorted((c for c in candidatos if c.aprovado), key=lambda c: -c.pontos):
        filas.setdefault(c.tag, []).append(c)
    return filas


def motivo_nao_cabe(c: Candidato, aceitos: list[Candidato], filtros: dict) -> str | None:
    if len(aceitos) >= filtros["max_por_tag"]:
        return "aprovado, mas não coube (limite da tag)"
    loja = c.oferta.shop_id or c.oferta.loja
    if sum(1 for x in aceitos if (x.oferta.shop_id or x.oferta.loja) == loja) >= filtros["max_por_loja_por_tag"]:
        return "aprovado, mas a loja já tem o máximo na tag"
    max_sem = filtros.get("max_sem_historico_por_tag", filtros["max_por_tag"])
    if c.veredito.status == "sem_historico" and \
            sum(1 for x in aceitos if x.veredito.status == "sem_historico") >= max_sem:
        return "aprovado, mas já há muitos 'a confirmar' na tag"
    lim = filtros.get("similaridade_duplicado", 0.75)
    if any(similaridade(c.oferta.nome, x.oferta.nome) >= lim for x in aceitos):
        return "aprovado, mas repetido (produto muito parecido)"
    return None


def selecionar(candidatos: list[Candidato], filtros: dict) -> dict[str, list[Candidato]]:
    """Selecao simples (sem reconferencia/memoria), usada na demo e nos testes."""
    saida: dict[str, list[Candidato]] = {}
    for tag, fila in filas_por_tag(candidatos).items():
        aceitos = saida.setdefault(tag, [])
        for c in fila:
            if motivo_nao_cabe(c, aceitos, filtros) is None:
                aceitos.append(c)
    return saida