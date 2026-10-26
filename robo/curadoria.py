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


# --- bloqueio por PEDACOS do nome (45a/46a rodadas) ------------------------------------------
# 1) separa o que o vendedor grudou: maiuscula no meio ('BicoSilicone'), letra/numero ('Mamadeira260ml')
# 2) cada pedaco vai para o singular ('copos' -> 'copo')
# 3) termo procurado como sequencia de pedacos inteiros OU grudado DENTRO de um mesmo pedaco
#    ('kitmamadeira'), aceitando plural em cada palavra do termo - nunca juntando pedacos vizinhos
#    (46a: 'Estampa Pinhas' juntado virava 'estampapinhas' e barrava como 'papinha')
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_LETRA_NUMERO = re.compile(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])")
_MIN_GRUDADO = 6  # termo curto ('arma', 'vape', 'chuca') so como pedaco inteiro: 'armario', 'machucado'
_LIGACAO = r"(?:de|do|da|dos|das|com|para|em)?"
_PALAVRAS_LIGACAO = {"de", "do", "da", "dos", "das", "com", "para", "em"}


def _singular_bloqueio(p: str) -> str:
    """_singular + plural em -is ('infantis' -> 'infantil', 'juvenis' -> 'juvenil'): so no bloqueio."""
    if len(p) > 5 and p.endswith("is") and not p.endswith(("ais", "eis", "ois")):
        return p[:-2] + "il"
    return _singular(p)


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c))


def pedacos_bloqueio(nome: str, camel: bool = True) -> list[str]:
    """Os pedacos do nome para o bloqueio: separados, minusculos, sem acento, no singular.
    camel=False nao separa pela maiuscula (caixa misturada 'unPAPINHa' quebraria o termo)."""
    t = _sem_acento(nome)
    if camel:
        t = _CAMEL.sub(" ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    t = _LETRA_NUMERO.sub(" ", t)
    return [_singular_bloqueio(p) for p in t.split()]


_CACHE_TERMO: dict = {}


def _regex_termo(frase: str):
    """Termo sobre o texto dos pedacos separados por espaco: entre as palavras do termo, espaco,
    nada (grudado) ou uma ligacao ('de', 'em'...); plural opcional em cada palavra. Termo de 6+
    letras pode vir grudado num prefixo ('kitmamadeira', 'kitbicos ortodontico'); termo curto so
    como palavra inteira. Nenhuma palavra do termo e partida por espaco: 'estampa pinha' nao e
    'papinha' (46a rodada)."""
    if frase in _CACHE_TERMO:
        return _CACHE_TERMO[frase]
    palavras = [p for p in raiz(frase).split() if p not in _PALAVRAS_LIGACAO]
    padrao = None
    if palavras:
        sep = rf"(?: ?{_LIGACAO} ?)"
        corpo = sep.join(re.escape(p) + r"(?:s|es)?" for p in palavras)
        if len("".join(palavras)) >= _MIN_GRUDADO:
            padrao = re.compile(corpo)
        else:
            padrao = re.compile(rf"(?<![a-z0-9]){corpo}(?![a-z])")
    _CACHE_TERMO[frase] = padrao
    return padrao


def _tem_termo(pedacos: list[str], frase: str) -> bool:
    alvo = raiz(frase).split()
    if not alvo:
        return False
    n = len(alvo)
    if any(pedacos[i:i + n] == alvo for i in range(len(pedacos) - n + 1)):
        return True
    padrao = _regex_termo(frase)
    return bool(padrao) and bool(padrao.search(" ".join(pedacos)))


def _tem_combinado(pedacos: list[str], palavra: str, contexto: list[str], exceto: list[str] | None = None) -> bool:
    """'bico' + contexto: os dois como pedacos inteiros, ou grudados num pedaco so ('bicosilicone',
    'bicoslatex', 'bicodemamadeira', 'bicosiliconeinfantil'). 'bicolor' nao e 'bico'. `exceto`
    (ex.: confeitar, bolo) tira o produto do combinado: 'saco de confeitar com bico de silicone'
    e utensilio de cozinha (47a rodada)."""
    if any(_tem_termo(pedacos, x) for x in exceto or []):
        return False
    p = raiz(palavra)
    ctx = [raiz(c).replace(" ", "") for c in contexto]
    tem_ctx = any(_tem_termo(pedacos, c) for c in contexto)
    # a palavra em QUALQUER lugar do pedaco, com plural/diminutivo ('kitbicos', 'biquinho',
    # 'bicosilicone'), mas nunca 'bicolor' (48a rodada: exigir o comeco do pedaco perdia 'kitbicos')
    forma = _FORMAS_COMBINADO.get(p) or re.compile(rf"{re.escape(p)}(?:s|es)?")
    for pedaco in pedacos:
        for m in forma.finditer(pedaco):
            if pedaco[m.end():].startswith("lor"):  # bicolor
                continue
            resto = re.sub(rf"^{_LIGACAO}", "", pedaco[m.end():])
            if tem_ctx or (resto and any(resto.startswith(c) for c in ctx)):
                return True
    return False


def menciona_sem_contexto(nome: str, combinados: dict | None) -> str | None:
    """Trava RIGIDA do 'Montar postagem' (49a rodada): a palavra de uma regra combinada ('bico',
    'bicos', 'biquinho') em QUALQUER lugar do nome ja barra, mesmo sem o contexto - a nao ser pelas
    excecoes da propria regra (confeitaria, bico de pato). Na rodada automatica vale a regra com
    contexto; no manual, bloquear a mais so faz escolher outro produto."""
    for grupo, regras in (combinados or {}).items():
        if grupo.startswith("_"):
            continue
        for regra in regras:
            if not regra.get("rigido_no_manual"):  # so 'bico' (protetor/copo sozinhos sao produtos comuns)
                continue
            p = raiz(regra["palavra"])
            forma = _FORMAS_COMBINADO.get(p) or re.compile(rf"{re.escape(p)}(?:s|es)?")
            for pedacos in (pedacos_bloqueio(nome), pedacos_bloqueio(nome, camel=False)):
                pedacos = _sem_acessorio_limpeza(pedacos)  # 'escova de mamadeira e bico' nao e bico
                if any(_tem_termo(pedacos, x) for x in regra.get("exceto") or []):
                    continue
                for pedaco in pedacos:
                    if any(not pedaco[m.end():].startswith("lor") for m in forma.finditer(pedaco)):
                        return NOMES_BLOQUEIO.get(grupo, f"bloqueado: {grupo}")
    return None


# Trava por RAIZ do "Montar postagem" nas tags de bebe/maternidade (51a rodada: cada rodada achava
# um titulo real novo; lista de termos nao fecha). Qualquer pedaco com uma destas raizes barra; os
# acessorios conhecidos saem antes. Bloquear a mais no manual so faz escolher outro produto.
_RAIZES_ALIMENTACAO = re.compile(  # nas tags bebe e maternidade
    r"mamadeir|chupet|chuquinh|^chucas?$|bi(?:co|cos|quinho|quinhos)(?!lor)|mamil|seio|copo|caneca|"
    r"transica|trainer|treinament|aprendiz|antivazament|formula|leite|papinh|alimentador|mingau|^mama$|"
    r"amament?ador|sippy|canudo")
# em QUALQUER tag do manual (52a rodada: escolher 'cozinha' desligava a trava): marcas de
# alimentacao infantil e palavras que so existem nesse tipo de produto
_RAIZES_ALIMENTACAO_TODA_TAG = re.compile(
    r"mamadeir|chupet|chuquinh|mamil|antivazament|aprendiz|transica|trainer|treinament|papinh|sippy|"
    r"^nuk$|^lillo$|^avent$|^mam$|^kuka$|^chicco$|^tommee$|^tippee$|^pigeon$|^evenflo$|^munchkin$|"
    r"^nuby$|^buba$|^clingo$|^medela$|^comtec$|^nestogeno$|^aptamil$|^enfamil$|^similac$|^milupa$|^mucilon$")
_ACESSORIOS_PERMITIDOS_MANUAL = re.compile(
    r"absorvente(?: ?(?:de|para|p))? ?seio[a-z]*|sutia[a-z]*(?: ?(?:de|para))? ?amamentacao|"
    r"almofada(?: ?(?:de|para))? ?amamentacao|travesseiro(?: ?(?:de|para))? ?amamentacao")


def raiz_de_alimentacao(nome: str, combinados: dict | None = None, toda_tag: bool = False) -> str | None:
    """A raiz de alimentacao infantil que aparece no nome (para o aviso), ou None. As excecoes das
    regras combinadas valem aqui tambem ('presilha bico de pato', confeitaria). toda_tag=True usa o
    conjunto que vale em qualquer tag (marcas e palavras exclusivas de alimentacao infantil)."""
    raizes = _RAIZES_ALIMENTACAO_TODA_TAG if toda_tag else _RAIZES_ALIMENTACAO
    excecoes = [x for regras in (combinados or {}).values() if isinstance(regras, list)
                for regra in regras for x in regra.get("exceto") or []]
    for pedacos in (pedacos_bloqueio(nome), pedacos_bloqueio(nome, camel=False)):
        excecao = any(_tem_termo(pedacos, x) for x in excecoes)
        texto = _ACESSORIOS_PERMITIDOS_MANUAL.sub(" ", " ".join(_sem_acessorio_limpeza(pedacos)))
        for pedaco in texto.split():
            m = raizes.search(pedaco)
            if m and not (excecao and m.group(0).startswith("bi")):  # excecao so livra o 'bico'
                return m.group(0)
        # 53a rodada: copo/caneca de crianca em qualquer tag ('Caneca ... Infantil' na tag cozinha)
        if toda_tag and _COPO.search(texto) and _CRIANCA.search(texto):
            return "copo/caneca infantil"
    return None


_COPO = re.compile(r"(?:^| )\S*(?:copo|caneca|garrafinha|squeeze)")
_CRIANCA = re.compile(r"(?:^| )\S*(?:infantil|infantis|bebe|baby|kids|kid|crianca|menino|menina|toddler)")


# plural e diminutivo das palavras das regras combinadas
_FORMAS_COMBINADO = {"bico": re.compile(r"bi(?:co|quinho|quinhos|cos|cao|coes)")}


def _radicais(bloqueios: dict) -> list[str]:
    """Radical de cada termo de UMA palavra com 7+ letras ('mamadeira' -> 'mamadeir', 'chupeta' ->
    'chupet', 'papinha' -> 'papinh'): barra diminutivo, aumentativo, plural e grudado ('Chupetinha',
    'mamadeirinhas', 'kitchupetas') - 47a rodada. Termo curto ('chuca') fica so como palavra."""
    vistos = []
    for grupo, lista in bloqueios.items():
        if grupo.startswith("_"):
            continue
        for termo in lista:
            palavras = raiz(termo).split()
            if len(palavras) == 1 and len(palavras[0]) >= 7:
                radical = re.sub(r"[aeiou]+$", "", palavras[0])
                if len(radical) >= 5:
                    vistos.append((grupo, radical))
    return vistos


def verificar_bloqueio(nome: str, bloqueios: dict, combinados: dict | None = None) -> str | None:
    """Barra se o termo aparece em QUALQUER das duas leituras do nome (com e sem separar pela
    maiuscula): bloquear a mais so tira o produto da tela; deixar NBCAL passar nao pode."""
    # combinado: tira so o acessorio de limpeza ("escova de mamadeira e bico"); porta/suporte ficam
    brutas = tuple(_sem_acessorio_limpeza(p) for p in (pedacos_bloqueio(nome), pedacos_bloqueio(nome, camel=False)))
    leituras = tuple(_sem_acessorio(p) for p in brutas)  # termos simples: acessorio de mamadeira sai
    for grupo, lista in bloqueios.items():
        if grupo.startswith("_"):
            continue
        if any(_tem_termo(pedacos, p) for pedacos in leituras for p in lista):
            return NOMES_BLOQUEIO.get(grupo, f"bloqueado: {grupo}")
    for grupo, radical in _radicais(bloqueios):  # radical dentro de qualquer pedaco
        if any(radical in pedaco for pedacos in leituras for pedaco in pedacos):
            return NOMES_BLOQUEIO.get(grupo, f"bloqueado: {grupo}")
    for grupo, regras in (combinados or {}).items():
        if grupo.startswith("_"):
            continue
        for regra in regras:
            # combinado olha o nome BRUTO: o acessorio nao apaga o contexto ('porta mamadeira com bico')
            if any(_tem_combinado(pedacos, regra["palavra"], regra["com"], regra.get("exceto"))
                   for pedacos in brutas):
                return NOMES_BLOQUEIO.get(grupo, f"bloqueado: {grupo}")
    return None


# Acessorio de mamadeira NAO e mamadeira (48a rodada: 'Bolsa termica porta mamadeirinhas' era
# barrado). O trecho do acessorio sai do nome ANTES do bloqueio; se sobrar mamadeira de verdade
# ('porta mamadeira com 2 mamadeiras'), continua barrado.
_ACESSORIO = re.compile(
    r"(?:porta|escova|escovinha|secador|secadora|escorredor|cesto|suporte|organizador|esterilizador|aquecedor)"
    r"(?: ?(?:de|da|do|para|p))? ?mamadeir[a-z]*")


# acessorio de LIMPEZA/SECAGEM "de mamadeira e bico" e um produto so (50a rodada: 'Escova para
# Mamadeira e Bico' e escova). Porta/suporte nao entram aqui: 'porta mamadeira com bico' segue barrado.
_ACESSORIO_LIMPEZA = re.compile(  # ate 3 palavras no meio: 'escova de limpeza para mamadeiras' (51a)
    r"(?:escova|escovinha|secador|secadora|escorredor|esterilizador|cesto)"
    # 55a rodada: 'com' NAO conta - 'escova COM mamadeira' e kit que traz a mamadeira junto
    r"(?: (?:de|da|do|para|p|limpeza|lavar|secar|giratoria|silicone|nylon|esponja)){0,4} ?mamadeir[a-z]*"
    r"(?: ?(?:e|e de|e para) ?bi(?:co|cos|quinho|quinhos))?")


def _sem_acessorio(pedacos: list[str]) -> list[str]:
    texto = _ACESSORIO_LIMPEZA.sub(" ", " ".join(pedacos))
    return _ACESSORIO.sub(" ", texto).split()


def _sem_acessorio_limpeza(pedacos: list[str]) -> list[str]:
    return _ACESSORIO_LIMPEZA.sub(" ", " ".join(pedacos)).split()


def _raiz_bloqueio(nome: str) -> str:
    return " ".join(pedacos_bloqueio(nome))


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