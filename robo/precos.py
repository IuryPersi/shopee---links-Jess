"""Detector de desconto falso (v2).

A Shopee mostra "-50%" calculado sobre um "preco de" que o proprio vendedor define.
Aqui o desconto so e real se o NOSSO historico provar. Regras (fechadas contra os
contraexemplos da auditoria de 17/10/2026):

1. Leituras viram UM preco por dia (mediana do dia): rodar 5x num dia nao pesa 5x.
2. O trecho atual de preco (dias seguidos ja neste nivel) e a PROMOCAO VIGENTE e nao
   entra na referencia — senao a promocao longa contamina o proprio "preco normal".
3. Referencia = dias ANTES da promocao vigente. Precisa de cobertura real: N dias
   distintos espalhados por M dias (tres leituras numa hora nao sao historico).
4. Preco normal = percentil 75 da referencia (resiste a gangorra e a quedas pontuais).
5. Piso = segundo menor preco diario da referencia (preco que ja durou 2+ dias). O
   desconto e medido contra min(normal, piso): se o produto so voltou a um preco que
   ja teve (gangorra, "inflou e voltou"), nao e achado.
6. Variacao-isca: se so a variacao mais barata (priceMin) caiu e a mais cara nao,
   o "desconto" e da variacao que o vendedor usa de vitrine.
Sem referencia suficiente -> "sem_historico": nunca anunciamos queda que nao vimos.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from statistics import median

DIA = 86400


@dataclass
class RegrasPreco:
    janela_dias: int = 30            # historico considerado
    min_dias_referencia: int = 3     # dias distintos ANTES da promocao vigente
    min_cobertura_dias: float = 4.0  # e abrangendo pelo menos isso ENTRE si
    queda_minima: float = 0.15       # abaixo do preco normal para contar como queda real
    tolerancia_nivel: float = 0.03   # precos a ate 3% um do outro sao o "mesmo nivel"
    subida_suspeita: float = 0.15    # alta recente acima da base antiga = maquiagem
    queda_brusca: float = 0.15       # queda contra o dia anterior (<= 36 h) = possivel relampago
    abertura_variacao: float = 1.3   # priceMax/priceMin acima disso = produto com variacoes de preco

    @classmethod
    def de_dict(cls, d: dict | None) -> "RegrasPreco":
        d = d or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Veredito:
    status: str               # menor_preco | queda_real | sem_historico | preco_de_sempre |
                              # preco_recorrente | subiu_antes | variacao_isca
    rotulo: str               # texto curto para a vitrine
    aceito: bool              # passa no filtro de honestidade de preco
    preco_normal: float | None = None
    queda_real: float | None = None   # fracao abaixo do preco normal
    queda_brusca: bool = False
    dias_historico: float = 0.0
    leituras: int = 0
    dias_em_promocao: int = 0

    @property
    def confirmado(self) -> bool:
        """Queda comprovada pelo historico (pode ir para a legenda)."""
        return self.status in ("menor_preco", "queda_real")


def _dia(ts: float) -> tuple[int, int]:
    t = time.localtime(ts)
    return t.tm_year, t.tm_yday


def _percentil(valores: list[float], q: float) -> float:
    v = sorted(valores)
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * q
    i = int(pos)
    frac = pos - i
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * frac


def _por_dia(hist: list[tuple]) -> list[tuple[float, float, float, float]]:
    """[(ts_do_dia, mediana_min, mediana_max, menor_leitura_do_dia)] — um ponto por dia."""
    dias: dict[tuple[int, int], list] = {}
    for item in hist:
        ts, pmin = item[0], item[1]
        pmax = item[2] if len(item) > 2 and item[2] else pmin
        dias.setdefault(_dia(ts), []).append((ts, pmin, pmax))
    saida = []
    for leituras in dias.values():
        saida.append((max(t for t, _, _ in leituras),
                      median(p for _, p, _ in leituras),
                      median(m for _, _, m in leituras),
                      min(p for _, p, _ in leituras)))
    return sorted(saida)


def _piso(precos: list[float]) -> float | None:
    """SEGUNDO menor preco diario da referencia: um preco que o produto ja teve em pelo
    menos 2 dias. Um relampago de um dia so nao rebaixa a referencia; mas gangorra
    (100/60 alternado), preco que volta (100,104,108 -> 150 -> 100) ou promocao repetida
    rebaixam — afirmar desconto contra um valor acima disso seria enganoso.
    E sempre <= ao "menor preco sustentado por 2 dias seguidos" (regra da 3a rodada),
    entao e estritamente mais conservador (4a rodada do Codex: gangorra diaria)."""
    if len(precos) < 2:
        return None
    return sorted(precos)[1]

def avaliar(atual: float, historico: list[tuple], agora: float,
            regras: RegrasPreco | None = None, aceitar_sem_historico: bool = True,
            atual_max: float | None = None) -> Veredito:
    """historico = [(ts, preco_min[, preco_max])] ANTERIOR a leitura atual."""
    r = regras or RegrasPreco()
    atual_max = atual_max or atual
    hist = [h for h in historico if agora - r.janela_dias * DIA <= h[0] < agora - 60 and h[1] > 0]
    diario = _por_dia(hist)
    hoje = _dia(agora)
    diario = [d for d in diario if _dia(d[0]) != hoje]  # o dia de hoje e o "agora"

    # queda brusca: contra o ultimo dia lido nas ultimas 36 h
    brusca = bool(diario) and agora - diario[-1][0] <= 1.5 * DIA and \
        atual <= diario[-1][1] * (1 - r.queda_brusca)

    referencia, promo = _separar_promocao(diario, atual, r)
    precos_ref = [d[1] for d in referencia]
    # cobertura = quanto tempo as leituras de referencia ABRANGEM entre si (nao ate hoje)
    cobertura = (referencia[-1][0] - referencia[0][0]) / DIA if referencia else 0.0
    idade = (agora - referencia[0][0]) / DIA if referencia else 0.0
    base = dict(queda_brusca=brusca, dias_historico=round(idade, 1), leituras=len(hist),
                dias_em_promocao=len(promo))

    if not referencia and promo and len(promo) >= r.min_dias_referencia and \
            (promo[-1][0] - promo[0][0]) / DIA >= r.min_cobertura_dias:
        # todo o historico ja neste nivel: e o preco normal dele, nao promocao
        base["dias_historico"] = round((agora - promo[0][0]) / DIA, 1)
        return Veredito("preco_de_sempre", "Preço de sempre: o desconto é só de vitrine", False,
                        preco_normal=round(median(d[1] for d in promo), 2), queda_real=0.0, **base)
    if len(referencia) < r.min_dias_referencia or cobertura < r.min_cobertura_dias:
        return Veredito("sem_historico", "Sem histórico suficiente: desconto a confirmar",
                        aceitar_sem_historico, **base)

    normal = _percentil(precos_ref, 0.75)
    piso = _piso([d[3] for d in referencia])  # usa a MENOR leitura de cada dia
    # referencia HONESTA: o desconto e medido contra min(normal, piso) — a leitura
    # mais conservadora possivel do "preco de antes".
    referencia_honesta = min(normal, piso) if piso is not None else normal
    queda = 1 - atual / referencia_honesta
    base.update(preco_normal=round(referencia_honesta, 2), queda_real=round(queda, 4))

    # "inflou e voltou": alta nos 7 dias antes da promocao contra a base mais antiga
    inicio_promo = promo[0][0] if promo else agora
    antigos = [d[1] for d in referencia if d[0] < inicio_promo - 7 * DIA]
    recentes = [d[1] for d in referencia if d[0] >= inicio_promo - 7 * DIA]
    if antigos and recentes:
        base_antiga = median(antigos)
        if median(recentes) > base_antiga * (1 + r.subida_suspeita) and \
                atual >= base_antiga * (1 - r.queda_minima):
            return Veredito("subiu_antes", "Subiu antes de 'baixar': desconto maquiado", False, **base)

    if piso is not None and piso < normal and queda < r.queda_minima:
        return Veredito("preco_recorrente", "Já esteve neste preço (ou perto) no mês", False, **base)
    if queda < r.queda_minima:
        return Veredito("preco_de_sempre", "Preço de sempre: o desconto é só de vitrine", False, **base)

    # variacao-isca: a mais barata caiu, a mais cara nao acompanhou
    if atual_max > atual * r.abertura_variacao:
        normal_max = _percentil([d[2] for d in referencia], 0.75)
        if 1 - atual_max / normal_max < r.queda_minima / 2:
            return Veredito("variacao_isca", "Só a variação mais barata caiu de preço", False, **base)

    dias_txt = max(1, round(idade))
    # "menor preco" = abaixo de TODA leitura bruta da janela (inclusive as de hoje e as
    # que a mediana do dia esconderia), nao so dos agregados
    if atual < min(h[1] for h in hist) * (1 - 0.01):
        return Veredito("menor_preco", f"Menor preço em {dias_txt} dias", True, **base)
    return Veredito("queda_real", f"{round(queda * 100)}% abaixo do preço de referência", True, **base)


def _separar_promocao(diario: list, atual: float, r: RegrasPreco) -> tuple[list, list]:
    """Divide os dias em (referencia, promocao_vigente).

    Promocao vigente = o trecho final em que TODOS os dias ficaram claramente abaixo do
    preco de antes (P75 da referencia * (1 - queda_minima)). Escolhe o corte mais antigo
    que satisfaz isso — assim uma promocao que melhora (60 -> 55) nao contamina a
    referencia. Sem esse trecho, a promocao e so o final ja no nivel do preco atual."""
    for i in range(r.min_dias_referencia, len(diario)):
        ref = diario[:i]
        if (ref[-1][0] - ref[0][0]) / DIA < r.min_cobertura_dias:
            continue  # referencia curta demais: tenta um corte mais adiante
        teto = _percentil([d[1] for d in ref], 0.75) * (1 - r.queda_minima)
        if all(d[1] <= teto for d in diario[i:]):
            return ref, diario[i:]
    i = len(diario)
    while i > 0 and diario[i - 1][1] <= atual * (1 + r.tolerancia_nivel):
        i -= 1
    return diario[:i], diario[i:]