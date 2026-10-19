"""Textos prontos para colar: nome enxuto, preco em reais e legenda.

Regras (auditoria juridica 17/10/2026):
- CONAR (Guia de Influenciadores): publicidade identificada LOGO NA PRIMEIRA LINHA,
  visivel sem tocar em "mais"; afiliado/comissao e publicidade.
- CDC arts. 31 e 37: a legenda so fala em % de desconto quando o NOSSO historico
  comprova a queda. O "-X%" anunciado pela Shopee nunca vai para a legenda.
"""
from __future__ import annotations

import re
import unicodedata

from .curadoria import Candidato
from . import vocabulario as _vocab

# Letras de outros alfabetos que SE PARECEM com latinas ("оff" com o cirilico, "Desсonto"
# com c cirilico): viram a latina antes da deteccao (antecipacao da 15a rodada).
_CONFUSAVEIS = str.maketrans(
    "АВЕКМНОРСТУХаеорсухіјѕԁɡΑΒΕΖΗΙΚΜΝΟΡΤΥΧαεικνορτυχ",
    "ABEKMHOPCTYXaeopcyxijsdgABEZHIKMNOPTYXaeikvoptux",
)


def _equivalente(ch: str) -> str:
    """Qualquer sinal de porcentagem Unicode vira "%" e qualquer simbolo de moeda vira "$"
    (11a rodada do Codex: o "٪" arabe nao e coberto pelo NFKC)."""
    if ch.isascii():
        return ch
    latina = ch.translate(_CONFUSAVEIS)
    if latina != ch:
        return latina
    if ch in "\u2044\u2215\uff0f\u29f8":  # barras de fracao/divisao Unicode viram "/" (23a rodada)
        return "/"
    if unicodedata.category(ch) == "Sc":
        return "$"
    nome = unicodedata.name(ch, "")
    if "PERCENT" in nome or "PER MILLE" in nome or "PER TEN THOUSAND" in nome:
        return "%"
    return ch


def _nfkc(s: str) -> str:
    """Normaliza Unicode de compatibilidade ("７０％" vira "70%"), unifica sinais de
    porcentagem e moeda e REMOVE caracteres invisiveis de formatacao (categoria Cf, ex.:
    U+200B no meio de "pre<U+200B>co" - 14a rodada). Todo texto da legenda passa por aqui."""
    t = unicodedata.normalize("NFKC", s or "")
    return "".join(_equivalente(c) for c in t if unicodedata.category(c) != "Cf")


# Lixo que os vendedores poem no titulo: grupos entre colchetes/parenteses (saem ANTES do
# corte por alegacao) e palavras soltas (saem DEPOIS, para nao esconder a alegacao do corte)
_COLCHETES = re.compile(r"(\[[^\]]*\]|【[^】]*】|\([^)]*\)|\b(?:fotos?|imagens?|v[ií]deos?)\s+reai?s?\b)",
                        re.IGNORECASE)
_RUIDO = re.compile(
    r"\b(envio imediato|pronta entrega|frete gr[aá]tis|promo[cç][aã]o|oferta|lan[cç]amento|"
    r"super promo|queima de estoque|original|novo|nova)\b",
    re.IGNORECASE,
)

# Alegacao de preco/promocao do VENDEDOR no titulo ("70% OFF", "R$ 19,90", "menor preco"):
# nunca vai para a legenda; o unico desconto publicado e o que o nosso historico provou
# (7a rodada do Codex: "Kit Potes 70% OFF" publicava 70% com queda real de 40%).
_ALEGACAO = re.compile(
    r"(-?\s*\d{1,3}(?:[.,]\d+)?\s*%(?:\s*(?:off|de\s+desconto|desc\.?|desconto))?|"
    r"\bat[eé]\s+\d{1,3}\s*%|"
    r"r\$\s*\d+(?:[.,]\d+)*|"
    r"\b(?:\d+\s*)?off\b|\bdescontos?\b|\bmenor\s+pre[cç]o\b|\bmais\s+barat[oa]s?\b|\bbarat[ií]ssim[oa]s?\b|"
    r"\bpre[cç]o\s+de\s+f[aá]brica\b|\bblack\s*friday\b|\bliquida[cç][aã]o\b|\bimperd[ií]vel\b|"
    r"\boferta\s+rel[aâ]mpago\b|\brel[aâ]mpago\b|\bcupo(?:m|ns)\b)",
    re.IGNORECASE,
)

# Rede de seguranca ESTRUTURAL (8a rodada do Codex: "pela metade do preco", "de 199,90 por
# 50,00"): se depois da limpeza ainda houver QUALQUER sinal de alegacao de preco, o titulo
# e cortado nesse ponto (vendedor poe a promessa no fim). Lista curta e ampla de proposito:
# cortar demais e aceitavel, publicar promessa nao comprovada nao.
_SUSPEITO = re.compile(
    r"%|r\$|\bpre[cç]os?\b|\bmetade\b|\bdescontos?\b|\boff\b|\bgr[aá]tis\b|\bbrindes?\b|"
    r"\bpromo\w*|\bpague\b|\bleve\s+\d|\bganhe\b|\b\d+\s*por\s*\d|\bde\s+\d+(?:[.,]\d+)?\s+por\b|"
    r"\bbarat\w*|\bqueima\b|"
    r"\bliquida\w*|\bimperd\w*|\bcupo\w*|\bblack\s*friday\b|\brel[aâ]mpago\b|\bsald[aã]o\b|\boferta\w*|"
    # antecipacao da 15a rodada: ingles/espanhol, preco sem unidade e urgencia
    r"\bsale\b|\bdeals?\b|\bcheap\w*|\bfree\s+shipping\b|\bde\s+gra[cç]a\b|\bbaix(?:ou|aram|ando)\b|"
    r"\bcaiu\b|\bestoque\s+limitad\w*|\b[uú]ltimas\s+(?:unidades|pe[cç]as)\b|\bacabando\b|"
    r"\b(?:s[oó]|apenas|somente)\s+\$?\s*\d|\bpor\s+(?:s[oó]|apenas|somente)\b|"
    r"\bp\.\s*c\.?\s*(?:de\s+)?\d|"  # 21a rodada: "p.c. de 70 pontos"
    # 15a rodada: linguagem de pagamento e preco "solto" (por 19 no Pix, a partir de 19, 19,9)
    r"\bpix\b|\b[aà]\s+vista\b|\bsem\s+juros\b|\bparcel\w*|\bboleto\b|"
    # "por N", "a partir de N" e decimais soltos: tratados por _alegacao_numerica (16a rodada)
    r"\bsem\s+custo\b|"
    # 26a rodada: gratuidade e comparativo de valor (classes, sem numero)
    r"\bgratuit\w*|\bgratuidade\b|\bsem\s+pagar\b|\bnada\s+a\s+pagar\b|\bna\s+faixa\b|\bpor\s+conta\s+da\s+casa\b|"
    r"\bcortesia\b|(?<!hands )(?<!hands-)\bfree\b(?!\s*(?:size|style))|\bde\s+gra[cç]a\b|"
    r"\b(?:menor|melhor|baixo|super)\s+valor\b|\bvalor\s+m[ií]nimo\b|\bimbat[ií]ve\w*|\bmais\s+em\s+conta\b|"
    r"\bcabe\s+no\s+(?:seu\s+)?bolso\b|\bem\s+conta\b",
    re.IGNORECASE,
)
# 9a rodada do Codex ("Economize 70 por cento", "#GanheBrinde"): fecha por CLASSE, nao por
# frase. (1) numero seguido de unidade de alegacao; (2) radicais de linguagem promocional.
_NUMERO_EXTENSO = (r"um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|"
                   r"quatorze|catorze|quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|"
                   r"cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|duzentos|trezentos|"
                   r"quatrocentos|quinhentos|seiscentos|setecentos|oitocentos|novecentos|mil|metade")
_NUMERO_ALEGACAO = re.compile(
    # numero (algarismo OU por extenso, 14a rodada) + unidade de alegacao, em qualquer grafia
    r"(?:\d+(?:[.,]\d+)?|\b(?:" + _NUMERO_EXTENSO + r")\b)\s*"
    r"(?:%|por\s*[-/]?\s*cento|p\s*/\s*cento|porcento|per\s*cent|pct\b|p\.\s*c\.?|reais\b|real\b|"
    r"centavos?\b|pratas?\b|pilas?\b|contos?\b|brl\b|usd\b|euros?\b|d[oó]lar(?:es)?\b|off\b|"
    r"x\s+mais\s+barato|x\s+de\b|no\s+pix\b|[aà]\s+vista\b)|"
    r"\b(?:brl|usd|eur|us\$|u\$)\s*\d",
    re.IGNORECASE,
)
# 15a rodada: numero COLADO a unidade de dinheiro/percentual, no texto compacto (pega
# "VinteReais", "70 p c t", "19 r e a i s", "70 0ff"); a unidade tolera leetspeak.
_UNIDADE_GRUDADA = (r"(?:r[e3][a4@][i1l]s|c[e3]nt[a4@]v[o0]s?|p[e3]rc[e3]nt|p[o0]rc[e3]nt[o0]|pct|brl|usd|"
                    r"[e3]ur[o0]s?|d[o0]l[a4]r[e3]s|pr[a4]t[a4]s|pil[a4]s?|c[o0]nt[o0]s|r\$|vista|pix)")
_COMPACTO_NUM = re.compile(
    r"(?:\d|" + _NUMERO_EXTENSO.replace("[eê]", "[eê]") + r")" + _UNIDADE_GRUDADA + r"|(?:brl|usd|eur|us\$|u\$|r\$)\d"
)
# 14a rodada: radical LONGO procurado tambem no texto COMPACTO (sem espacos/pontuacao), o que
# fecha "menor p r e c o", "menor pr eco", "des-con-to". So radicais que nao se formam pela
# juncao de duas palavras legitimas (nada de "preco" sozinho: "sempre colorido").
_COMPACTO = re.compile(
    r"menorpre[cç]|descont|porcento|pcento|promo[cç][aã]|liquida[cç][aã]|rel[aâ]mpago|"
    r"fretegr[aá]tis|blackfriday|pechinch|economiz|imperd[ií]ve|queimadeestoque|apenasr\$",
)
RADICAIS_PROMO = (
    "econom", "ganh", "brind", "aproveit", "imperd", "barat", "desconto", "descont", "promo",
    "oferta", "liquida", "metade", "dobro", "gratis", "grátis", "frete", "cupom", "cupon",
    "relampago", "relâmpago", "saldao", "saldão", "menor preco", "menor preço", "preco",
    "preço", "pague", "leve", "so hoje", "só hoje", "ultimas unidades", "últimas unidades",
    "por apenas", "apenas r", "exclusiv", "garanta", "corre ", "off", "%", "r$", "custo benef",
)


# radicais no INICIO de palavra, todas as ocorrencias (10a rodada: find() so via a 1a).
# off/%/r$/leve/preco ficam com as regex de palavra inteira (nao cortar "offset", "levedura").
_RADICAIS_RE = re.compile(
    r"(?<![^\W_])(?:" + "|".join(re.escape(r) for r in RADICAIS_PROMO
                                 if r not in ("off", "%", "r$", "leve", "preco", "preço")) + ")",
    re.IGNORECASE,
)


# estes podem aparecer colados no meio de palavra ("MegaEconomia", "SuperDesconto") sem
# risco de cortar nome legitimo; os demais so valem no inicio da palavra ("queimador" fica)
_EM_QUALQUER_LUGAR = re.compile(
    # 12a rodada (MenorPrecoGarantido, MenorPrecos): radicais que nunca aparecem dentro de
    # palavra legitima de produto valem em QUALQUER posicao e com qualquer sufixo.
    # Excecoes conhecidas: "precoce/precocidade" (13a rodada: (?!c) era largo demais e
    # deixava "MenorPrecoComprovado") e "liquidificador" (liquida[cç]).
    r"econom|descont|promo[cç]|oferta|brinde|gr[aá]tis|barat|oportunidade|pre[cç]o(?!ces?\b|cidade)|"
    r"menor\s*pre[cç]|\$\s*\d|"
    r"liquida[cç]|imperd|rel[aâ]mpago|cupo[mn]|frete|metade|blackfriday|black\s+friday|sald[aã]o|"
    r"descuent|rebaj|discount|clearance|outlet|bargain|pechinch",
    re.IGNORECASE,
)
# leetspeak no texto compacto ("d3sc0nt0", "pr0m0ç@o")
_LEET = str.maketrans("013457@", "oieasta")


# ---------------------------------------------------------------------------------------
# 16a rodada do Codex: NUMEROS deixam de ser tratados por lista de grafias. Um analisador
# le o titulo token a token; para cada numero (algarismo, decimal ou por extenso, inclusive
# colado: "UmReal", "19reais", "10x") examina os tokens seguintes JUNTANDO letras soltas e
# desfazendo leetspeak ("r e a l", "r3al", "dól ares", "0ff") e os anteriores ("por",
# "a partir de", "so", "BRL", "USD"). Numero de ESPECIFICACAO (anos, cm, litro, pecas...)
# e liberado por lista de PERMITIDOS, nao de proibidos.
_NUMWORDS = sorted({
    "um", "uma", "dois", "duas", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez",
    "onze", "doze", "treze", "quatorze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito",
    "dezenove", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa",
    "cem", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
    "oitocentos", "novecentos", "mil",
    # 26a rodada: zero, femininos das centenas e milhao/bilhao
    "zero", "duzentas", "trezentas", "quatrocentas", "quinhentas", "seiscentas", "setecentas", "oitocentas",
    "novecentas", "milhao", "milhoes", "bilhao", "bilhoes",
}, key=len, reverse=True)
_UNID_PREFIXO = ("reais", "real", "centav", "prata", "conto", "pila", "dolar", "euro", "percent", "porcent",
                 "pontospercent", "pontopercent", "cartao", "dinheiro", "boleto", "vista", "parcel", "vez",
                 "credit", "debit", "cash", "transfer", "mensa", "mensal", "anuais", "semanais", "prazo",
                 # 19a rodada: toda periodicidade de cobranca (semanas/anos continuam como medida)
                 "semanal", "anual", "quinzen", "bimestr", "trimestr", "semestr", "diari", "diaria",
                 "quadrimestr", "bienal", "bienais", "bissemanal", "bissemana")
_MOEDAS_ISO = {"brl", "usd", "eur", "gbp", "ars", "jpy", "cny", "cad", "aud", "chf", "mxn", "clp", "cop", "pen",
               "uyu", "pyg", "bob", "rs"}
# ISO 4217 (codigos ativos) + cripto comuns: qualquer um deles e moeda, em qualquer caixa
_MOEDAS_ISO |= set("""aed afn all amd ang aoa ars aud awg azn bam bbd bdt bgn bhd bif bmd bnd bob bov brl bsd btn bwp
byn bzd cad cdf che chf chw clf clp cny cop cou crc cuc cup cve czk djf dkk dop dzd egp ern etb eur fjd fkp gbp gel
ghs gip gmd gnf gtq gyd hkd hnl hrk htg huf idr ils inr iqd irr isk jmd jod jpy kes kgs khr kmf kpw krw kwd kyd kzt
lak lbp lkr lrd lsl lyd mad mdl mga mkd mmk mnt mop mru mur mvr mwk mxn mxv myr mzn nad ngn nio nok npr nzd omr pab
pen pgk php pkr pln pyg qar ron rsd rub rwf sar sbd scr sdg sek sgd shp sle sll sos srd ssp stn svc syp szl thb tjs
tmt tnd top try ttd twd tzs uah ugx usd usn uyi uyu uyw uzs ved ves vnd vuv wst xaf xag xau xcd xof xpf yer zar zmw
zwl btc eth usdt usdc bnb xrp ada doge""".split())
# codigos ISO que colidem com palavra de produto do nicho ficam de fora ("Mop" de limpeza)
_MOEDAS_ISO -= {"mop", "all"}
_UNID_EXATA = {"off", "pc", "pct", "pix", "cada", "pesos", "libras", "ienes", "iene", "yen", "yuan", "francos",
               "franco", "rupias", "wons", "rublos", "liras", "bitcoins", "bitcoin"} | _MOEDAS_ISO
_MOEDA_ANTES = ("brl", "usd", "eur", "rs")
# 18a rodada: moeda por extenso ANTES do valor ("reais dezenove hoje", "reais: 19")
_MOEDA_EXTENSO_ANTES = ("reais", "real", "dolar", "dolares", "euro", "euros", "centavos")
# "Couro Real 2 Pecas", "Fotos Reais 3 Unidades": real/reais como ADJETIVO depois destas palavras
# 20a rodada: a unica excecao que sobra e "couro real" (fotos/imagens reais saem como ruido)
_REAL_ADJETIVO_APOS = {"couro"}
# 20a rodada: palavras de dinheiro/percentual/periodicidade que, a ate 16 tokens de QUALQUER
# numero (antes OU depois), cortam o titulo. "prata" (cor) e "real" (adjetivo) ficam de fora.
# 21a rodada: UMA lista so, valendo antes e depois do numero (antes, cada lado tinha a sua)
_MOEDAS_NOMES = {"pesos", "peso", "libras", "libra", "iene", "ienes", "yen", "yuan", "renminbi", "franco", "francos",
                 "rupia", "rupias", "won", "wons", "rublo", "rublos", "lira", "liras", "rand", "shekel", "shekels",
                 "dirham", "dirhams", "bitcoin", "bitcoins", "btc", "satoshi", "guarani", "guaranis", "bolivar",
                 "bolivares", "coroa", "coroas", "escudo", "escudos", "soles", "kwanza", "kwanzas", "dinar", "dinares",
                 "dinars", "rial", "riais", "rials", "dong", "baht", "forint", "zloty", "zlotys", "kuna", "taka",
                 "ringgit", "rupiah", "cordoba", "cordobas", "lempira", "lempiras", "quetzal", "quetzales",
                 "balboa", "balboas", "gourde", "cruzeiro", "cruzeiros", "cruzado", "cruzados", "pataca", "patacas",
                 "afghani", "manat", "tenge", "lari", "hryvnia", "naira", "cedi", "cedis", "xelim", "xelins",
                 "shilling", "shillings", "dalasi", "kina", "vatu", "tala", "paanga", "rufiyaa", "ouguiya", "ariary",
                 "leone", "leones", "birr", "nakfa", "florim", "florins", "guilder", "guilders", "pesetas",
                 "dracma", "dracmas", "marcos", "lev", "leva", "leu", "lei", "kip", "riel", "som", "somoni", "dram"}
_PERTO_EXATO = {"reais", "real", "centavo", "centavos", "dolar", "dolares", "euro", "euros", "conto", "contos",
                "pila", "pilas", "pix", "boleto", "cash", "anual", "anuais", "pct", "pc"} | _MOEDAS_ISO | _MOEDAS_NOMES
# codigos de produto com letra+digito que podem ficar; siglas de 3 letras que NAO sao moeda
_CODIGOS_PRODUTO = {"a4", "a3", "a5", "mp3", "mp4", "h2o", "usb2", "usb3", "4k", "8k", "5g", "4g", "3d", "2d"}
_SIGLAS_PRODUTO = {"led", "usb", "pvc", "mdf", "abs", "rgb", "eva", "pet", "bpa", "aco", "kit", "tam", "cor", "uni",
                   "inox", "dvd", "lcd", "uhd", "fhd", "ips", "nfc", "gps", "aaa", "ipx", "pro", "max", "top",
                   "mix", "set", "box", "fit", "eco", "new", "air", "bag", "gel", "kid", "bio", "spa", "zen", "duo"}
_PERTO_PREFIXO = ("percent", "porcent", "centua", "credit", "debit", "parcel", "mensal", "mensais", "semanal",
                  "semanais", "quinzen", "bimestr", "trimestr", "quadrimestr", "semestr", "bienal", "bienais",
                  "bissemana", "diari", "cartao", "dinheiro", "transfer", "prazo")
_PERTO_TODOS = tuple(_PERTO_EXATO) + _PERTO_PREFIXO
_PERTO_EXATO_NOMES = _PERTO_EXATO - _MOEDAS_ISO
_JANELA = 16
_APOS_NUMERO_CORTA = {"por", "via", "ao", "cada", "p", "pelo", "pela"}  # 19 por unidade/mes, 19 via ...
_GATILHO_ANTES = ("por", "so", "apenas", "somente", "custa", "partirde", "apartirde")
# 17a rodada: o numero so FICA no nome se o que vem depois for claramente inofensivo.
_FISICO = {  # medidas e tempo: unicos permitidos depois de "por/a partir de" ou de decimal
    "ano", "anos", "mes", "meses", "dia", "dias", "hora", "horas", "h", "min", "minutos", "seg",
    "semana", "semanas", "noite", "noites", "cm", "mm", "m", "metro", "metros", "km", "kg", "g", "gr",
    "mg", "ml", "l", "lt", "litro", "litros", "w", "v", "mah", "gb", "tb", "pol", "polegada", "polegadas",
}
_ESPECIFICACAO = _FISICO | {
    "peca", "pecas", "pcs", "un", "und", "unid", "unidade", "unidades", "item", "itens", "lugar", "lugares",
    "porta", "portas", "gaveta", "gavetas", "boca", "bocas", "camada", "camadas", "nivel", "niveis",
    "velocidade", "velocidades", "par", "pares", "rolo", "rolos", "folha", "folhas", "cor", "cores", "fio",
    "fios", "andar", "andares", "divisoria", "divisorias", "compartimento", "compartimentos",
}
_LETRA_UNIDADE = {"m", "l", "g", "h", "v", "w"}
_TEMPO = {"dia", "dias", "semana", "semanas", "mes", "meses", "ano", "anos", "hora", "horas", "noite", "noites",
          "h", "hs", "hr", "hrs", "min", "mins", "minuto", "minutos", "seg", "segs", "segundo", "segundos",
          "quinzena", "quinzenas", "d", "ds", "dd", "sem", "sems"}
_LIGACAO = {"no", "na", "a", "em", "de", "ate"}
_NUMSET = set(_NUMWORDS)
_LEET_LETRAS = str.maketrans("013457@", "oieasta")


def _plano(s: str) -> str:
    t = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# 23a rodada: o que pode vir DEPOIS de um numero para ele ficar no nome. Medidas e
# quantidades + substantivos comuns de produto do nicho (mais as palavras das tags, que o
# config registra ao carregar). Moeda/giria/codigo nunca estao aqui, por construcao.
_PERMITIDOS_APOS_NUMERO = set(_ESPECIFICACAO) | {
    "caixa", "caixas", "pote", "potes", "body", "bodies", "bodys", "refil", "refis", "cabide", "cabides", "toalha",
    "toalhas", "fralda", "fraldas", "tamanho", "tamanhos", "modelo", "modelos", "prato", "pratos", "copo", "copos",
    "taca", "tacas", "xicara", "xicaras", "talher", "talheres", "colher", "colheres", "garfo", "garfos", "faca",
    "facas", "panela", "panelas", "frigideira", "frigideiras", "tampa", "tampas", "forma", "formas", "assadeira",
    "assadeiras", "pano", "panos", "esponja", "esponjas", "escova", "escovas", "balde", "baldes", "vassoura",
    "rodo", "mop", "saco", "sacos", "sacola", "sacolas", "bolsa", "bolsas", "brinco", "brincos", "anel", "aneis",
    "colar", "colares", "pulseira", "pulseiras", "calcinha", "calcinhas", "sutia", "sutias", "meia", "meias",
    "pijama", "pijamas", "vestido", "vestidos", "blusa", "blusas", "conjunto", "conjuntos", "macacao",
    "macacoes", "mijao", "mijoes", "babador", "babadores", "mordedor", "mordedores", "manta", "mantas", "lencol",
    "lencois", "fronha", "fronhas", "travesseiro", "travesseiros", "almofada", "almofadas", "tapete", "tapetes",
    "cortina", "cortinas", "cesto", "cestos", "organizador", "organizadores", "organizadora", "organizadoras",
    "nicho", "nichos", "prateleira", "prateleiras", "gancho", "ganchos", "prendedor", "prendedores", "presilha",
    "presilhas", "elastico", "elasticos", "laco", "lacos", "tiara", "tiaras", "pincel", "pinceis", "pecinha",
    "pecinhas", "potinho", "potinhos", "frasco", "frascos", "garrafa", "garrafas", "jarra", "jarras", "caneca",
    "canecas", "marmita", "marmitas", "pacote", "pacotes", "rolinho", "rolinhos", "saquinho", "saquinhos",
    "inox", "aco", "aluminio", "silicone", "bambu", "madeira", "vidro", "plastico", "algodao", "couro",
    "polegada", "polegadas", "andares", "lugares", "fases", "fase", "posicoes", "posicao", "funcoes", "funcao",
    "queimador", "queimadores", "roupa", "roupas", "roupinha", "roupinhas", "boneca", "bonecas", "acessorio",
    "acessorios", "alca", "alcas", "utensilio", "utensilios", "ventosa", "ventosas", "divisor", "divisores", "bandeja", "bandejas",
}


_PERMITIDOS_BASE = frozenset(_PERMITIDOS_APOS_NUMERO)


def _palavra_de_dinheiro(p: str) -> bool:
    # palavra EXATA (ou plural) - "realista" nao e "real"; prefixos so os de percentual/periodo/pagamento
    return (p in _PERTO_EXATO or p in _UNID_EXATA or p in _MOEDAS_NOMES or p.startswith(_PERTO_PREFIXO)
            or p.rstrip("s") in _PERTO_EXATO | _MOEDAS_NOMES)


def registrar_vocabulario(palavras, recomecar: bool = False):
    """O config adiciona as palavras das tags (de uma palavra so) aos permitidos.
    24a rodada: nunca palavra de dinheiro/percentual/periodo nem sigla curta (<4 letras), e
    recomecar=True refaz a lista a partir da base (sem acumular configs anteriores)."""
    if recomecar:
        _PERMITIDOS_APOS_NUMERO.clear()
        _PERMITIDOS_APOS_NUMERO.update(_PERMITIDOS_BASE)
    for p in palavras:
        p = _plano(p).strip()
        if p and " " not in p and p.isalpha() and len(p) >= 4 and not _palavra_de_dinheiro(p):
            _PERMITIDOS_APOS_NUMERO.add(p)
            _PERMITIDOS_APOS_NUMERO.add(p + "s")


# 24a rodada: unidade ABREVIADA/singular (forma de preco por unidade) so vale logo depois
# de kit/com/inicio; quantidade no plural e substantivo de produto valem, MENOS quando uma
# das duas palavras anteriores e moeda (codigo ISO em qualquer caixa, nome de moeda, giria).
# Medida/tempo (_FISICO) vale sempre ("Gel 200ml").
_ANTES_DE_QUANTIDADE = {"kit", "com", "c", ""}
_UNIDADE_SINGULAR = {"un", "und", "unid", "unidade", "peca", "pc", "pcs", "item", "cada"}
_GIRIAS_DINHEIRO = {"pau", "paus", "mangos", "merreca", "grana", "bufunfa", "dindin", "conto", "contos",
                    "pila", "pilas", "pratas", "trocado", "trocados"}


def _eh_moeda(p: str) -> bool:
    return bool(p) and (p in _MOEDAS_ISO or p in _MOEDAS_NOMES or p in _GIRIAS_DINHEIRO or _palavra_de_dinheiro(p))


def _permitido_apos_numero(prox: str | None, anterior: str = "", anterior2: str = "") -> bool:
    if not prox:
        return False  # numero solto no fim
    if prox in _FISICO:
        return True
    couro_real = anterior == "real" and anterior2 in _REAL_ADJETIVO_APOS
    if (_eh_moeda(anterior) and not couro_real) or (_eh_moeda(anterior2) and anterior2 != "couro"):
        return False  # paus 19 un, GEL 19 un, coroas suecas 19 pecas, peso argentino 19 un
    if prox in _UNIDADE_SINGULAR:
        return anterior in _ANTES_DE_QUANTIDADE
    return prox in _PERMITIDOS_APOS_NUMERO or prox.rstrip("s") in _PERMITIDOS_APOS_NUMERO


def _eh_numero(t: str) -> bool:
    return t.isdigit() or t in _NUMSET or bool(re.fullmatch(r"\d+x\d*", t))


def _unidade_de_alegacao(seguintes: list[str]) -> bool:
    """Os tokens seguintes (ja planos) formam unidade de dinheiro/percentual/pagamento?
    Junta letras soltas e desfaz leet ("r e a l", "r3al", "r@al", "dol ares")."""
    cands, acum = [], ""
    for tok in seguintes[:16]:
        acum += tok.translate(_LEET_LETRAS)
        cands.append(acum)
    return any(c.startswith(p) for c in cands for p in _UNID_PREFIXO) or any(c in _UNID_EXATA for c in cands)


def _tokens(n: str) -> list[tuple[int, str, str]]:
    return [(m.start(), m.group(), _plano(m.group())) for m in re.finditer(r"[^\W_]+(?:@[^\W_]*)*|[$%@]", n)]


def _alegacao_numerica(n: str) -> int | None:
    toks = _tokens(n)
    i = _alegacao_numerica_idx(n, toks)
    if i is None:
        return None
    # recua para levar junto a expressao que introduz o numero ("por", "a partir de", "so", "em")
    while i > 0 and (toks[i - 1][2] in _GATILHO_ANTES + _MOEDA_ANTES + _MOEDA_EXTENSO_ANTES
                     + ("de", "a", "em", "partir", "no", "na", "$")
                     or toks[i - 1][2].endswith("partir")):
        i -= 1
    return toks[i][0]


def _palavra_monetaria_em(toks: list, k: int) -> bool:
    """O token k (juntando fragmentos seguintes: "re-ais", "r e a i s") forma palavra de
    dinheiro/percentual/periodicidade?"""
    if toks[k][2] == "real" and k > 0 and toks[k - 1][2] in _REAL_ADJETIVO_APOS:
        return False  # "couro real"
    if toks[k][2] in _MOEDAS_ISO and toks[k][2] not in _PERTO_EXATO_NOMES and not toks[k][1].isupper():
        return False  # "Gel Capilar 200ml": codigo ISO a distancia so conta em MAIUSCULAS (GEL, MAD)
    acum = ""
    for tok in toks[k:k + _JANELA]:
        acum += tok[2].translate(_LEET_LETRAS)
        if acum in _PERTO_EXATO or acum.startswith(_PERTO_PREFIXO):
            return True
        # continua juntando so enquanto o que ja juntou ainda PODE virar palavra da lista
        # ("c enta vos", "d olare s", "re-al", "r e a l"); senao encerra ("realista" para)
        if not any(s.startswith(acum) for s in _PERTO_TODOS):
            return False
    return False


def _alegacao_por_proximidade(toks: list) -> int | None:
    # numero = algarismos, extenso, ou token que COMECA com numero por extenso ("dezhoje")
    numeros = [k for k, tok in enumerate(toks) if _eh_numero(tok[2]) or tok[2][:1].isdigit()
               or any(tok[2].startswith(w) and len(w) >= 3 for w in _NUMWORDS)]
    if not numeros:
        return None
    for k in range(len(toks)):
        if _palavra_monetaria_em(toks, k):
            perto = [x for x in numeros if abs(x - k) <= _JANELA]
            if perto:
                return min([k] + perto)
    return None


def _alegacao_numerica_idx(n: str, toks: list) -> int | None:
    """Indice do token onde comeca a alegacao numerica (ou None). Lista de PERMITIDOS:
    o numero so passa seguido de palavra comum (que nao seja dinheiro), de unidade de
    medida/quantidade, ou de outro numero ('3 em 1', '0 a 12 meses', '50 x 70')."""
    prox_monet = _alegacao_por_proximidade(toks)  # 20a rodada: dinheiro perto de numero, antes OU depois
    if prox_monet is not None:
        return prox_monet
    i = 0
    while i < len(toks):
        _, cru, t = toks[i]
        # 22a rodada: letras SEGUIDAS de digitos no mesmo token ("GBP19", "conto19", "r3al19",
        # "pct70", "diaria19") cortam - salvo poucos codigos de produto conhecidos
        if re.search(r"[a-z@]\d", t) and t not in _CODIGOS_PRODUTO and not re.fullmatch(r"\d+x\d+[a-z]*", t):
            return i
        # 23a rodada: numero por extenso LONGO (5+ letras) colado a letras no mesmo token
        # corta sempre ("contovinteeum", "pratadezenove", "pctsetentahoje", "dezenoveMAD")
        if t not in _NUMSET and any(w in t for w in _NUMWORDS if len(w) >= 5 and w != t):
            return i
        # 24a rodada: token que COMECA com palavra de dinheiro/percentual seguida de numero
        # (algarismo ou extenso de qualquer tamanho): "contodezhoje", "pctcemhoje", "pcdezhoje"
        for stem in sorted(_PERTO_EXATO | _UNID_EXATA | _MOEDAS_NOMES | {"prata", "pratas"} | set(_PERTO_PREFIXO),
                           key=len, reverse=True):
            if t.startswith(stem) and len(t) > len(stem):
                r = t[len(stem):]
                if r[:1].isdigit() or any(r.startswith(w) for w in _NUMWORDS):
                    return i
        # palavra de dinheiro/percentual COLADA a numero por extenso: "contodezenove",
        # "pilavinte", "gbpdezenove", "pctsetenta", "diariadezenove"
        for w in _NUMWORDS:
            if t.endswith(w) and len(t) > len(w):
                pre = t[:-len(w)].translate(_LEET_LETRAS)
                if pre in _PERTO_EXATO or pre.startswith(_PERTO_PREFIXO) or pre in _UNID_EXATA:
                    return i
        # 22a rodada: sigla de 3 letras MAIUSCULAS ao lado de numero e tratada como moeda
        # (qualquer codigo ISO, inclusive os nao listados), salvo siglas comuns de produto
        if re.fullmatch(r"[A-Z]{3}", cru) and t not in _SIGLAS_PRODUTO:
            vizinhos = [toks[k][2] for k in (i - 1, i + 1) if 0 <= k < len(toks)]
            if any(_eh_numero(v) or v[:1].isdigit() for v in vizinhos):
                return i
        # gatilho/moeda colado a numero no MESMO token, com qualquer sufixo:
        # "pordezenove", "pordezenovehoje", "BRLVinte", "brlvinteeum", "USD19"
        for p in _GATILHO_ANTES + _MOEDA_ANTES + _MOEDA_EXTENSO_ANTES:
            if t.startswith(p) and len(t) > len(p):
                r = t[len(p):]
                if r[0].isdigit() or any(r.startswith(w) for w in _NUMWORDS):
                    return i
        # numero por extenso colado a dinheiro ou a outro numero: "UmReal", "vinteeum"
        if not t[:1].isdigit() and t not in _NUMSET:  # "dezenove" e numero, nao "dez"+"e"+"nove"
            for w in _NUMWORDS:
                if t.startswith(w) and len(t) > len(w):
                    r = t[len(w):]
                    if _unidade_de_alegacao([r]) or (r.startswith("e") and any(r[1:].startswith(x) for x in _NUMWORDS)):
                        return i
                    break
        anterior = toks[i - 1][2] if i > 0 else ""
        anterior2 = toks[i - 2][2] if i > 1 else ""
        # 19a rodada: moeda por extenso ANTES do valor corta SEMPRE (inclusive "reais 19 un",
        # "reais 19un"), salvo real/reais adjetivo ("Couro Real 2 Pecas")
        if anterior in _MOEDA_EXTENSO_ANTES and not (anterior == "real" and anterior2 in _REAL_ADJETIVO_APOS) and \
                (_eh_numero(t) or t[:1].isdigit()):
            return i - 1
        m = re.match(r"\d+", t)
        resto = t[m.end():] if m else ""
        if m and resto:  # algarismos colados a letras: "300ml" e "50x70cm" passam; "19reais", "19r3al" nao
            # "50x70cm" so passa como dimensao se terminar em MEDIDA ("2x19", "2x19real" nao)
            dim = re.fullmatch(r"x\d+(?:[.,]\d+)?([a-z]+)", resto)
            gat = (anterior in _GATILHO_ANTES or anterior in _MOEDA_ANTES or anterior == "$"
                   or (anterior == "de" and anterior2.endswith("partir")))
            fisico = resto in _FISICO or resto in _LETRA_UNIDADE or (dim and dim.group(1) in _FISICO)
            quantidade = resto in _ESPECIFICACAO and not ((_eh_moeda(anterior) and not (anterior == "real" and
                                                         anterior2 in _REAL_ADJETIVO_APOS)) or _eh_moeda(anterior2)) and \
                (resto not in _UNIDADE_SINGULAR or anterior in _ANTES_DE_QUANTIDADE)
            if gat and not fisico:
                return i  # 24a rodada: "custa 19un"
            if fisico or (quantidade and not gat):
                i += 1
                continue
            if resto != "x":
                return i
        if not (_eh_numero(t) or resto == "x"):
            i += 1
            continue
        gatilho = (anterior in _GATILHO_ANTES or anterior in _MOEDA_ANTES or anterior == "$"
                   or (anterior == "de" and anterior2.endswith("partir")))
        # decimal "19,90" / "2,80m": junta a parte depois da virgula
        j, decimal, extra = i, False, []
        if t.isdigit() and i + 1 < len(toks) and toks[i + 1][2][:1].isdigit() and \
                n[toks[i][0] + len(cru):toks[i + 1][0]] in (",", "."):
            decimal, j = True, i + 1
            m2 = re.match(r"\d+", toks[j][2])
            if toks[j][2][m2.end():]:
                extra = [toks[j][2][m2.end():]]  # "2,80m" -> unidade "m"
        # numero composto: "vinte e um", "19 mil", "19 e 90", "cento e vinte"
        composto = False
        while j + 1 < len(toks) and (toks[j + 1][2] == "mil" or
                                     (toks[j + 1][2] == "e" and j + 2 < len(toks) and _eh_numero(toks[j + 2][2])) or
                                     (toks[j + 1][2] in _NUMSET and toks[j][2] in _NUMSET)):
            j += 1
            composto = True
        if resto == "x":
            extra = ["x"]
        fracao = False
        if j + 1 < len(toks) and not extra and "/" in n[toks[j][0] + len(toks[j][1]):toks[j + 1][0]]:
            # barra apos numero = cobranca por periodo (19/mes, 19/30 dias), salvo fracao
            # CLASSICA (1/2, 3/4, 5/8: numerador < denominador em 2,3,4,8,16,32,64). A fracao
            # vira um numero so e passa por TODAS as checagens abaixo (22a rodada: o atalho
            # antigo pulava gatilho/pagamento e deixava "por 1/2", "1/2 cada mes").
            den = toks[j + 1][2]
            if not (t.isdigit() and den.isdigit() and den in {"2", "3", "4", "8", "16", "32", "64"}
                    and int(t) < int(den)):
                return i
            j += 1
            fracao = True
            if any(x[2] in _TEMPO or x[2] in ("ou", "durante") for x in toks[j + 1:j + 5]):
                return i  # 1/2 meses, 3/4 semanas, 19/32 longos dias, 1/2 ou 3 meses
        seguintes = extra + [x[2] for x in toks[j + 1:j + 17]]
        prox = seguintes[0] if seguintes else None
        prox2 = seguintes[1] if len(seguintes) > 1 else None
        if _unidade_de_alegacao(seguintes):
            return i  # 19 reais, 19 r e a l, 19 r@al, 70 pontos percentuais, 1/2 cada mes
        if any(r in "".join(seguintes[:16]).translate(_LEET_LETRAS) for r in ("percent", "porcent", "centua")):
            return i  # 70 pontos (de) porcentuais / per centual / p e r c e n t u a i s
        if fracao and prox is not None and (prox in _LIGACAO or len(prox) <= 2 or not prox.isalpha()):
            return i  # 19/32 d, 19/32 ds, 1/2 a 3 meses
        # ---- 23a rodada: decisao final por LISTA DE PERMITIDOS ----
        # O numero so FICA se o que vem depois for medida/quantidade ou substantivo de
        # produto conhecido (_PERMITIDOS_APOS_NUMERO), ou uma cadeia numerica legitima
        # ('3 em 1', '0 a 12 meses', '50 x 70 cm'). QUALQUER outra coisa corta - moeda,
        # giria ("paus", "mangos"), codigo ("gel", "mad"), periodo, palavra desconhecida.
        if gatilho or decimal or composto:
            if prox not in _FISICO:
                return i  # por 19 hoje, a partir de 19, 19,90 un, vinte e um ..., 19 mil ...
        elif prox in ("x", "a", "em", "ate") and prox2 and (_eh_numero(prox2) or prox2[:1].isdigit()):
            prox3 = seguintes[2] if len(seguintes) > 2 else ""
            prox3 = seguintes[2] if len(seguintes) > 2 else ""
            if prox == "em" and prox2 == "1" and t.isdigit() and 2 <= int(t) <= 10 \
                    and not prox3.startswith(("x", "vez")):
                i = j + 3  # "3 em 1" (19 em 1 vez nao)
                continue
            if prox2.endswith("x") or prox3.startswith(("x", "vez")):
                return i  # 19 em 2x, 19 em duas vezes
            i = j + (1 if extra else 2)  # cadeia: o proximo numero e avaliado na sua vez (e precisa passar)
            continue
        elif not _permitido_apos_numero(prox, anterior if i > 0 else "", anterior2):
            return i
        i = j + 1
    return None

def tem_alegacao(texto: str) -> bool:
    """O MESMO detector do corte do titulo: a vitrine nunca diz que cortou sem ter cortado."""
    return _primeira_alegacao(_nfkc(texto)) is not None


def _primeira_alegacao(n: str) -> int | None:
    """Posicao do primeiro sinal de alegacao no titulo (n ja normalizado por _nfkc)."""
    pos = [m.start() for m in (_SUSPEITO.search(n), _NUMERO_ALEGACAO.search(n), _RADICAIS_RE.search(n),
                               _EM_QUALQUER_LUGAR.search(n)) if m]
    mapa = [(i, c) for i, c in enumerate(n.lower()) if c.isalnum() or c in "%$@"]
    compacto = "".join(c for _, c in mapa)
    for texto in (compacto, compacto.translate(_LEET)):  # mesma posicao: so troca caractere
        m = _COMPACTO.search(texto)
        if m:
            pos.append(mapa[m.start()][0])
    m = _COMPACTO_NUM.search(compacto)  # numero (com os algarismos) colado a unidade
    if m:
        pos.append(mapa[m.start()][0])
    p_num = _alegacao_numerica(n)  # analisador de numeros (16a rodada)
    if p_num is not None:
        pos.append(p_num)
    if not pos:
        return None
    i = min(pos)
    while i > 0 and not n[i - 1].isspace():  # corta no inicio da PALAVRA ("MegaEconomia" sai inteira)
        i -= 1
    return i


_CAUDA = re.compile(r"(\s+(a\s+partir|partir|conserva\s+por|de|da|do|das|dos|pela|pelo|por|com|e|a|o|ao|aos|ate|até|para|um|uma|sua|seu|sua|essa|esse|nossa|nosso|na|no|em|x|-|\||/|\+|,))+\s*$",
                    re.IGNORECASE)

# palavras que tornam um texto do config (hashtag) uma alegacao promocional
_PROMO_CONFIG = ("off", "desconto", "preco", "preço", "barat", "promo", "gratis", "grátis",
                 "metade", "cupom", "black", "liquida", "queima", "relampago", "relâmpago", "%",
                 "sale", "deal", "pechinch", "outlet", "descuent", "discount", "baixou", "oferta")


def cupom_seguro(texto: str) -> str:
    """Cupom do config vira SO o codigo (letras/numeros). Frase como "70% OFF em tudo" e
    recusada: valor e regras do cupom quem diz e a Shopee, no app."""
    s = _nfkc(texto).strip().upper()
    if not s:
        return ""
    if not re.fullmatch(r"[A-Z0-9]{3,20}", s):
        raise ValueError(f"legenda.cupom_do_dia deve ser só o código do cupom (letras e números): {texto!r}")
    return s


def _sem_promo_colado(texto: str) -> bool:
    """Para texto sem espacos (hashtag, nome de tag): radical promocional em qualquer posicao."""
    # 15a rodada: o config passa pelo DETECTOR COMPLETO (separado por _ e camelCase, e
    # compacto), nao por uma lista propria - "#SetentaReais" e "#Setenta_Por_Cento" caem
    n = _nfkc(texto)
    separado = re.sub(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Þ])", " ", n).replace("_", " ").replace("#", " ")
    t = re.sub(r"[^a-z0-9à-ÿ%$]", "", n.lower())
    radicais = set(_PROMO_CONFIG) | {r.replace(" ", "") for r in RADICAIS_PROMO}
    return (not any(r in t for r in radicais) and _primeira_alegacao(separado) is None
            and _primeira_alegacao(t) is None)


def hashtag_segura(tag: str) -> str:
    t = _nfkc(tag).strip()
    if not re.fullmatch(r"#[A-Za-zÀ-ÿ_]{2,40}", t) or not _sem_promo_colado(t):
        raise ValueError(f"hashtag recusada (formato ou alegação promocional): {tag!r}")
    return t


def validar_textos_do_config(cfg: dict):
    """Tudo do nicho.json que vai para a legenda tem formato rigido (9a rodada do Codex)."""
    leg = cfg.get("legenda", {})
    cupom_seguro(leg.get("cupom_do_dia", ""))
    for h in leg.get("hashtags") or []:
        hashtag_segura(h)
    for chave, t in cfg.get("tags", {}).items():
        if not re.fullmatch(r"[a-z]{3,20}", chave) or not _sem_promo_colado(_nfkc(chave)):
            raise ValueError(f"nome de tag inválido (só letras minúsculas, sem alegação): {chave!r}")
        emoji = t.get("emoji", "")
        e = _nfkc(emoji)  # "７０％" vira "70%" e e recusado; qualquer letra/numero Unicode tambem
        if len(e) > 4 or any(ch.isalnum() or ch in "%$" for ch in e):
            raise ValueError(f"emoji da tag {chave!r} deve ser só emoji: {emoji!r}")
        rotulo = t.get("rotulo", chave)
        if not re.fullmatch(r"[A-Za-zÀ-ÿ ]{2,20}", _nfkc(rotulo)) or tem_alegacao(rotulo):
            raise ValueError(f"rótulo da tag {chave!r} inválido: {rotulo!r}")


AVISO_TOPO = "#publi · link de afiliado: ganho comissão se você comprar por ele, sem custo extra pra você."
AVISO_FIM = ("Preço, cupom e estoque são definidos pela Shopee e podem mudar a qualquer momento. "
             "Confira no link antes de comprar.")
AVISO_PRECO = AVISO_FIM


def reais(v: float | None) -> str:
    if v is None:
        return "—"
    s = f"{v:,.2f}"  # 1,234.56
    return "R$ " + s.replace(",", "§").replace(".", ",").replace("§", ".")


def milhar(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}".replace(".", ",").replace(",0", "") + " mil"
    return str(n)


# ---------------------------------------------------------------------------------------
# 25a rodada do Codex: GARANTIA ESTRUTURAL. Depois de 25 rodadas ficou provado que filtro de
# texto livre nao fecha por lista. Entao o nome que vai para a legenda NAO TEM NENHUM NUMERO
# DO VENDEDOR: nem algarismo, nem numero por extenso, nem numero colado a palavras, nem % ou
# $. Sem numero, nao ha como afirmar valor ou percentual - qualquer que seja a moeda, a
# giria ou o truque. O unico preco publicado e o NOSSO (linha "por R$ X", conferido).
_CONECTOR_NUMERICO = {"em", "a", "x", "ate", "ou", "e", "de", "por", "/"}
_PECAS_DE_VALOR = sorted(
    set(_NUMWORDS) | {p for p in (_PERTO_EXATO | _UNID_EXATA | _MOEDAS_NOMES | _GIRIAS_DINHEIRO | _MOEDAS_ISO)
                      if p.isalpha()} | {"hoje", "so", "agora", "cada", "por", "apenas", "e", "x", "pct", "pc"},
    key=len, reverse=True)


_PECAS_DE_VALOR = sorted(set(_PECAS_DE_VALOR) | {"mop", "all"}, key=len, reverse=True)  # colagem "cemmop"
_PECAS_DE_VALOR_SET = set(_PECAS_DE_VALOR) - set(_NUMWORDS)


def _so_pecas_de_valor(t: str) -> bool:
    """O token e INTEIRO uma colagem de numero por extenso + palavras de valor/moeda/giria
    ("umhoje", "vinteeum", "dezpaushoje", "cemgelhoje", "mangosdez")? Exige ao menos um numero.
    "Milho", "Setembro", "Vintage", "Umidificador" nao se decompoem assim e ficam."""
    t = re.sub(r"[^a-z]", "", t)
    if not t:
        return False
    alcanca = {0: False}  # posicao -> ja usou numero por extenso?
    for pos in range(len(t)):
        if pos not in alcanca:
            continue
        for p in _PECAS_DE_VALOR:
            if t.startswith(p, pos):
                fim = pos + len(p)
                alcanca[fim] = alcanca.get(fim, False) or alcanca[pos] or p in _NUMSET
    return alcanca.get(len(t), False)


_ROMANO = re.compile(r"(?=[mdclxvi]{2,}$)m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})")
_TAMANHOS_ROMANOS = {"xl", "xxl", "xxxl", "xxxxl"}  # tamanho de roupa, nao numero


def _tem_caractere_numerico(s: str) -> bool:
    """26a rodada: QUALQUER caractere que o Unicode define como numerico (algarismo de
    qualquer escrita, romano Ⅻ, chines 十/〇, tamil ௰, fracao bengali ৴, ½...)."""
    return any(unicodedata.numeric(c, None) is not None or unicodedata.category(c) in ("Nd", "Nl", "No")
               for c in s)


def _eh_token_numerico(cru: str, original: str = "") -> bool:
    p = _plano(cru)
    nucleo = re.sub(r"[^a-z0-9]", "", p)
    return (_tem_caractere_numerico(cru) or _tem_caractere_numerico(original) or "%" in cru or "$" in cru
            or nucleo in _NUMSET or _so_pecas_de_valor(nucleo)
            or (bool(_ROMANO.fullmatch(nucleo)) and nucleo not in _TAMANHOS_ROMANOS and cru.isupper()))


def _juntar_letras_soltas(toks: list[str]) -> list[str]:
    """26a rodada: "d e z paus", "v i n t e mangos" - letras soltas seguidas viram uma palavra
    para a avaliacao (e saem juntas se formarem numero)."""
    saida, k = [], 0
    while k < len(toks):
        if len(toks[k]) == 1 and toks[k].isalpha():
            m = k
            while m < len(toks) and len(toks[m]) == 1 and toks[m].isalpha():
                m += 1
            if m - k >= 2:
                saida.append("".join(toks[k:m]))
                k = m
                continue
        saida.append(toks[k])
        k += 1
    return saida


_MEIO = {"meio", "meia"}


def sem_numeros(n: str) -> str:
    """Remove todo numero do vendedor e o que so faz sentido com ele: '3 em 1', '0 a 12
    meses', '2,80m x 1,80m', 'Dois Lugares', '300ml', 'umhoje'. Palavras comuns ficam."""
    toks = _juntar_letras_soltas(n.split())
    # "meio real", "meia libra", "meioreal": meio/meia viram numero so perto de dinheiro
    # ("Meia-Calca", "Kit Meias" ficam)
    for k, tok in enumerate(toks):
        pl = re.sub(r"[^a-z]", "", _plano(tok))
        prox_pl = re.sub(r"[^a-z]", "", _plano(toks[k + 1])) if k + 1 < len(toks) else ""
        resto = pl[4:] if pl[:4] in _MEIO else None
        if (pl in _MEIO and (_eh_moeda(prox_pl) or prox_pl in _PECAS_DE_VALOR_SET)) or \
                (resto and (_eh_moeda(resto) or _so_pecas_de_valor("um" + resto) or resto in _PECAS_DE_VALOR_SET)):
            toks[k] = "1"
    saida, k = [], 0
    while k < len(toks):
        if not _eh_token_numerico(toks[k]):
            saida.append(toks[k])
            k += 1
            continue
        k += 1  # consome a corrida numerica: numero (conector numero)* (unidade)?
        while k < len(toks):
            atual = _plano(toks[k]).strip(".,:;!?-")
            if _eh_token_numerico(toks[k]):
                k += 1
            elif atual in _CONECTOR_NUMERICO and k + 1 < len(toks) and _eh_token_numerico(toks[k + 1]):
                k += 2
            elif atual in _ESPECIFICACAO or atual in _TEMPO:
                k += 1
                break
            elif _eh_moeda(re.sub(r"[^a-z]", "", atual)) or re.sub(r"[^a-z]", "", atual) in _PECAS_DE_VALOR_SET \
                    or re.sub(r"[^a-z]", "", atual).startswith(("percent", "porcent")):
                k += 1  # a palavra de dinheiro/percentual do numero sai junto ("reais", "libra", "paus")
                while k < len(toks) and (_eh_moeda(re.sub(r"[^a-z]", "", _plano(toks[k])))
                                         or re.sub(r"[^a-z]", "", _plano(toks[k])) in _MOEDAS_NOMES):
                    k += 1  # "pesos argentinos", "coroas suecas"
                break
            else:
                break
    return " ".join(saida)


_VOCAB_CONFIG: set[str] = set()


def registrar_vocabulario_legenda(palavras, recomecar: bool = False):
    """Palavras das tags tambem podem aparecer no nome publicado - se passarem nos filtros."""
    if recomecar:
        _VOCAB_CONFIG.clear()
    for frase in palavras:
        for p in str(frase).split():
            w = _vocab.normalizar_palavra(p)
            if len(w) >= 3 and not _palavra_de_dinheiro(w) and not tem_alegacao(w) and not _eh_moeda(w) \
                    and w not in _NUMSET and not _so_pecas_de_valor(w):
                _VOCAB_CONFIG.add(w)


def _no_vocabulario(tok: str) -> bool:
    if _vocab.normalizar_palavra(tok) in _vocab.COMPOSTOS and all(
            "a" <= c.lower() <= "z" or c in "-áàâãéêíóôõúç" for c in unicodedata.normalize("NFC", tok)):
        return True  # "Meia-Calça"
    partes = [x for x in re.split(r"[-/]", tok) if x]
    if not partes:
        return False
    for parte in partes:
        if any(not ("a" <= c.lower() <= "z" or unicodedata.combining(c) or c in "áàâãäéèêëíìîïóòôõöúùûüçñ.,:;!?'\"")
               for c in unicodedata.normalize("NFC", parte)):
            return False  # qualquer caractere fora do alfabeto latino (numeral, simbolo, outra escrita)
        w = _vocab.normalizar_palavra(parte)
        if not w:
            return False
        # 28a rodada: forma que e giria/nome de dinheiro ("pratas", "contos", "paus") nunca entra,
        # mesmo que o singular seja material/objeto permitido ("prata")
        if w in _GIRIAS_DINHEIRO or w in _MOEDAS_NOMES or _palavra_de_dinheiro(w):
            return False
        ok = (w in _vocab.PALAVRAS or w in _VOCAB_CONFIG
              or (w.endswith("s") and (w[:-1] in _vocab.PALAVRAS or w[:-1] in _VOCAB_CONFIG)))
        if not ok:
            return False
    return True


def so_vocabulario(n: str) -> str:
    """27a rodada: o nome publicado so tem palavras do vocabulario PERMITIDO (e conectores
    entre elas). Palavra fora - numero, romano, moeda, giria, gratuidade, comparativo,
    marca desconhecida - sai. Fecha por construcao o que lista de proibidos nao fecha."""
    saida = []
    for tok in n.split():
        w = _vocab.normalizar_palavra(tok)
        if w in _vocab.CONECTORES and all(c.isalpha() for c in tok.strip(".,:;")):
            saida.append(tok.strip(".,:;"))
        elif _no_vocabulario(tok.strip(".,:;!?")):
            saida.append(tok.strip(".,:;!?"))
    # conector so entre duas palavras do vocabulario
    limpo = []
    for k, tok in enumerate(saida):
        if _vocab.normalizar_palavra(tok) in _vocab.CONECTORES:
            if not limpo or k + 1 >= len(saida) or _vocab.normalizar_palavra(saida[k + 1]) in _vocab.CONECTORES:
                continue
            if _vocab.normalizar_palavra(limpo[-1]) in _vocab.CONECTORES:
                continue
        limpo.append(tok)
    return " ".join(limpo)


def nome_curto(nome: str, limite: int = 70) -> str:
    n = re.sub(r"\s+", " ", _COLCHETES.sub(" ", _nfkc(nome)))
    for _ in range(10):  # corta no primeiro sinal e repete ate nao sobrar nenhum
        corte = _primeira_alegacao(n)
        if corte is None:
            break
        n = _CAUDA.sub("", " " + n[:corte]).strip()
    n = re.sub(r"\s+", " ", _ALEGACAO.sub(" ", _RUIDO.sub(" ", n)))
    n = sem_numeros(n)  # 25a rodada: garantia estrutural - nenhum numero do vendedor
    n = so_vocabulario(n)  # 27a rodada: so palavras do vocabulario permitido
    n = _CAUDA.sub("", " " + n).strip()
    n = re.sub(r"\s*[-|/,+]+\s*$", "", n).strip(" -|/,+")
    if len(n.split()) < 2 or _primeira_alegacao(n) is not None or any(_eh_token_numerico(x) for x in n.split()):
        n = ""  # quase nada sobrou, ou ainda ha alegacao: nome generico, nunca a alegacao
    if not n:  # titulo era so alegacao: nome generico em vez de repetir a alegacao
        n = "Produto"
    if len(n) <= limite:
        return n
    corte = n[:limite].rsplit(" ", 1)[0]
    return (corte or n[:limite]).rstrip(" -|/,+") + "…"


def linha_preco(c: Candidato) -> str:
    o, v = c.oferta, c.veredito
    prefixo = "a partir de " if tem_variacoes(o) else ""
    texto = f"por {prefixo}{reais(o.preco_min)}"
    if v.confirmado and v.queda_real:
        texto += f" ({round(v.queda_real * 100)}% abaixo do preço normal)"
    return texto


def tem_variacoes(o) -> bool:
    """O anuncio tem opcoes com precos diferentes (o preco mostrado e o da mais barata).
    31a rodada do Codex: QUALQUER diferenca conta (antes, ate 1% passava como preco unico);
    meio centavo de folga so absorve ruido de ponto flutuante."""
    return (o.preco_max or 0) - (o.preco_min or 0) > 0.005


def preco_de_por(c: Candidato) -> tuple[float | None, float, int | None]:
    """(preco_de, preco_por, % de queda). 'De' SO quando o nosso historico comprova a queda
    (preco de referencia honesto); senao None - nunca o 'de' inflado do vendedor."""
    o, v = c.oferta, c.veredito
    if v.confirmado and v.preco_normal and v.queda_real:
        return v.preco_normal, o.preco_min, round(v.queda_real * 100)
    return None, o.preco_min, None


def mensagem(c: Candidato, emoji: str = "🔥", canal: str = "link", cupom: str = "",
             hashtags: list[str] | None = None) -> str:
    """Mensagem CURTA do dia a dia (WhatsApp, story, Telegram): o produto, quanto era e
    quanto esta, a prova social e o link. #publi na primeira linha (CONAR)."""
    o = c.oferta
    de, por, pct = preco_de_por(c)
    linhas = ["#publi · link de afiliado", f"{emoji} {nome_curto(o.nome)}"]
    if de:
        # 30a rodada do Codex: com variacoes de preco, o De/Por e da opcao MAIS BARATA (o historico
        # acompanha o menor preco) - dizer isso, nunca apresentar como preco unico
        if tem_variacoes(o):
            linhas.append(f"Opção mais barata: de {reais(de)} por {reais(por)} (-{pct}%)")
        else:
            linhas.append(f"De {reais(de)} por {reais(por)} (-{pct}%)")
    else:
        prefixo = "a partir de " if tem_variacoes(o) else ""
        linhas.append(f"Por {prefixo}{reais(por)}")
    prova = []
    if o.nota is not None:
        prova.append(f"⭐ {str(round(o.nota, 1)).replace('.', ',')}")
    if o.vendas:
        prova.append(f"{milhar(o.vendas)} vendidos")
    if prova:
        linhas.append(" · ".join(prova))
    cupom = cupom_seguro(cupom)
    if cupom:
        linhas.append(f"🎟️ Cupom {cupom} (confira no app)")
    linhas.append(f"👉 {c.link}" if canal == "link" else "🔗 Link nos stories")
    linhas.append("Preço pode mudar a qualquer momento.")
    return "\n".join(linhas)


def legenda(c: Candidato, emoji: str = "🔥", canal: str = "link", cupom: str = "",
            hashtags: list[str] | None = None) -> str:
    """canal='link' (stories/WhatsApp/Telegram, com link) ou 'feed' (sem link clicavel)."""
    o, v = c.oferta, c.veredito
    linhas = [AVISO_TOPO, "", f"{emoji} {nome_curto(o.nome)}", f"💸 {linha_preco(c)}"]
    if v.confirmado:
        linhas.append(f"✅ {v.rotulo} (pelo nosso acompanhamento)")
        if v.queda_brusca:
            linhas.append("⚡ Caiu forte nas últimas horas")
    cupom = cupom_seguro(cupom)
    if cupom:
        linhas.append(f"🎟️ Cupom {cupom} (confira valor, regras e validade no app)")
    prova = []
    if o.nota is not None:
        prova.append(f"⭐ {str(round(o.nota, 1)).replace('.', ',')}")
    if o.vendas:
        prova.append(f"{milhar(o.vendas)} vendidos")
    if prova:
        linhas.append(" · ".join(prova))
    linhas.append(f"👉 {c.link}" if canal == "link" else "🔗 Link nos stories e na bio")
    linhas.append("")
    linhas.append(AVISO_FIM)
    tags = [hashtag_segura(h) for h in (hashtags if hashtags is not None else ["#achadinhos", "#shopee"])]
    if c.tag:
        tags.append(f"#{c.tag}")
    linhas.append(" ".join(tags))
    return "\n".join(linhas)
