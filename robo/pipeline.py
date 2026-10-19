"""Uma rodada completa:
coletar (gravando historico pagina a pagina) -> julgar preco -> curar -> para cada vaga:
nao repetir o que ja foi sugerido -> reconferir o preco na Shopee -> gerar link rastreado
-> salvar vitrine/csv/legendas. Se a coleta quebrar, a ultima vitrine boa fica intacta."""
from __future__ import annotations

import re
import shutil
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .banco import JANELA_MESMA_LEITURA, Banco
from .curadoria import Candidato, avaliar_candidato, filas_por_tag, motivo_nao_cabe
from .precos import DIA, RegrasPreco, avaliar
from .shopee_api import ErroShopee, Oferta
from .vitrine import salvar_saidas

# Erro de conta/credencial: nao adianta seguir buscando, aborta a rodada.
FATAIS = {10020, 10031, 10032, 10033, 10034, 10035, 11002}


class ErroColeta(RuntimeError):
    """A coleta nao funcionou (rede fora, Shopee fora): nada de vitrine nova."""


@dataclass
class Resultado:
    lidas: int = 0
    escolhidos: dict = field(default_factory=dict)
    top: list = field(default_factory=list)
    recusados: Counter = field(default_factory=Counter)
    erros: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    saida_parcial: bool = False
    arquivos: dict = field(default_factory=dict)
    chamadas: int = 0
    links_sem_conferencia: int = 0  # a Shopee nao respondeu na conferencia: foram SEM o selo

    @property
    def total_escolhidos(self) -> int:
        return sum(len(v) for v in self.escolhidos.values())


def coletar(cliente, banco: Banco, cfg: dict, agora: float, log: Callable = print):
    col = cfg["coleta"]
    max_falhas = int(col.get("max_falhas_seguidas", 6))
    ofertas: dict[int, Oferta] = {}
    origens: dict[int, set] = {}
    erros: list[str] = []
    ok = falhas_seguidas = 0
    for tag, t in cfg["tags"].items():
        for termo in t["buscas"]:
            for ordem in col["ordenacoes"]:
                for pagina in range(1, int(col["paginas_por_termo"]) + 1):
                    try:
                        lote, tem_mais = cliente.buscar_ofertas(
                            keyword=termo, sort_type=ordem, page=pagina, limit=col["itens_por_pagina"])
                    except ErroShopee as e:
                        if e.codigo in FATAIS:
                            banco.commit()
                            raise
                        erros.append(f"{tag}/{termo} p{pagina}: {e}")
                        log(f"  ! {tag}/{termo} p{pagina}: {e}")
                        falhas_seguidas += 1
                        if falhas_seguidas >= max_falhas:
                            banco.commit()
                            raise ErroColeta(f"{falhas_seguidas} buscas seguidas falharam (ultima: {e})") from None
                        break
                    ok += 1
                    falhas_seguidas = 0
                    for o in lote:
                        ofertas[o.item_id] = o  # a leitura mais recente vale
                        origens.setdefault(o.item_id, set()).add(tag)
                        banco.registrar(o, ts=agora, commit=False)
                    banco.commit()  # historico salvo a cada pagina: erro adiante nao perde o que ja veio
                    if not tem_mais:
                        break
        log(f"  {tag}: {sum(1 for s in origens.values() if tag in s)} produtos vistos")
    if ok == 0:
        raise ErroColeta("nenhuma busca funcionou")
    return ofertas, origens, erros


def historico_para_julgar(banco: Banco, o: Oferta, agora: float, janela_dias: int) -> list[tuple]:
    """Historico anterior + o MENOR preco que esta propria rodada ja viu do item, se for
    menor que o preco sendo julgado. Sem isso, duas buscas (60 e depois 61) ou coleta 60 +
    reconferencia 61 publicariam "menor preco" a 61 (5a rodada do Codex)."""
    hist = banco.historico(o.item_id, desde=agora - janela_dias * DIA, ate=agora)
    # toda leitura que PODE ter absorvido as desta rodada (o banco funde leituras numa
    # janela de 30 min, inclusive num registro gravado segundos antes de `agora`)
    da_rodada = banco.historico(o.item_id, desde=agora - JANELA_MESMA_LEITURA - 1, ate=agora + 3600)
    if da_rodada:
        menor = min(da_rodada, key=lambda x: x[1])
        if menor[1] < o.preco_min:
            hist.append((agora - 61, menor[1], menor[2]))
    return hist


def julgar(ofertas: dict[int, Oferta], origens: dict[int, set], banco: Banco, cfg: dict,
           agora: float) -> list[Candidato]:
    regras = RegrasPreco.de_dict(cfg.get("regras_preco"))
    aceitar = bool(cfg["filtros"].get("aceitar_sem_historico", True))
    candidatos = []
    for item_id, o in ofertas.items():
        hist = historico_para_julgar(banco, o, agora, regras.janela_dias)
        v = avaliar(o.preco_min, hist, agora, regras, aceitar, atual_max=o.preco_max)
        candidatos.append(avaliar_candidato(o, v, cfg, origens.get(item_id)))
    return candidatos


def montar_subids(modelo: list[str], tag: str) -> list[str]:
    """Shopee aceita ate 5 subIds; mantemos so letras e numeros."""
    saida = []
    for s in modelo[:5]:
        s = re.sub(r"[^A-Za-z0-9]", "", str(s).replace("{tag}", tag))
        if s:
            saida.append(s)
    return saida


def _buscar_item(c: Candidato, cliente) -> Oferta | None:
    """Consulta o item de novo na Shopee (None = sumiu)."""
    o = c.oferta
    lote, _ = cliente.buscar_ofertas(item_id=o.item_id, shop_id=o.shop_id, limit=1, sort_type=1)
    return next((x for x in lote if x.item_id == o.item_id), None)


def _repeticao(c: Candidato, banco: Banco, agora: float, f: dict) -> tuple[str | None, str]:
    """(motivo_para_pular, selo). Ja sugerido ha pouco so volta se baixou mais."""
    ult = banco.ultima_sugestao(c.oferta.item_id, antes_de=agora)
    if not ult:
        return None, "NOVO"
    if c.oferta.preco_min <= ult[1] * (1 - float(f.get("rebaixa_para_repetir", 0.05))):
        return None, "BAIXOU DE NOVO"
    if agora - ult[0] < float(f.get("nao_repetir_dias", 5)) * DIA:
        return f"já sugerido nos últimos {f.get('nao_repetir_dias', 5)} dias", ""
    return None, ""

def _link(c: Candidato, tag: str, cliente, banco: Banco, cfg: dict, agora: float, erros: list, log) -> str:
    col = cfg["coleta"]
    o = c.oferta
    sub_ids = montar_subids(col.get("subids", ["ig", "{tag}"]), tag)
    validade = float(col.get("validade_link_dias", 7)) * DIA
    link = banco.link_salvo(o.item_id, sub_ids, validade, agora)
    if link:
        c.link_rastreado = bool(sub_ids)
        return link
    if o.link_produto and (sub_ids or not o.link_oferta):
        try:
            link = cliente.link_curto(o.link_produto, sub_ids or None)
            banco.salvar_link(o.item_id, sub_ids, link, agora)
            c.link_rastreado = bool(sub_ids)
            return link
        except ErroShopee as e:
            if e.codigo in FATAIS:
                raise
            erros.append(f"link {o.item_id}: {e}")
            log(f"  ! link {o.item_id}: {e}")
    c.link_rastreado = False  # offerLink ja e da conta dela, mas sem os subIds
    return o.link_oferta


def preencher(filas: dict[str, list[Candidato]], cliente, banco: Banco, cfg: dict, agora: float,
              res: Resultado, rejulgar: Callable, log: Callable = print,
              verificador: Callable | None = None) -> dict[str, list[Candidato]]:
    f, col = cfg["filtros"], cfg["coleta"]
    reconferir = bool(col.get("reconferir_escolhidos", True))
    max_consultas = int(f["max_por_tag"]) + int(f.get("reserva_por_tag", 0))
    escolhidos: dict[str, list[Candidato]] = {}
    for tag, fila in filas.items():
        aceitos = escolhidos.setdefault(tag, [])
        consultas = 0
        for c in fila:
            motivo = motivo_nao_cabe(c, aceitos, f) or _repeticao(c, banco, agora, f)[0]
            if motivo:
                res.recusados[motivo] += 1
                continue
            if reconferir:
                if consultas >= max_consultas:
                    res.recusados["não reconferido: acabou a reserva da tag"] += 1
                    continue
                consultas += 1
                try:
                    novo = _buscar_item(c, cliente)
                except ErroShopee as e:
                    if e.codigo in FATAIS:
                        raise
                    res.erros.append(f"reconferir {c.oferta.item_id}: {e}")
                    res.recusados["erro na reconferência"] += 1  # sem conferir, nao entregamos
                    continue
                if novo is None:
                    res.recusados["sumiu da Shopee na reconferência"] += 1
                    continue
                banco.registrar(novo, ts=agora)  # o preco confirmado entra no historico
                if novo.preco_min > c.oferta.preco_min * 1.03:
                    res.recusados["preço subiu na reconferência"] += 1
                    continue
                # julgamento COMPLETO de novo com o preco atual (desconto, filtros, bloqueios)
                c2 = rejulgar(novo, c.origens)
                if not c2.aprovado:
                    res.recusados[f"na reconferência: {c2.recusa}"] += 1
                    continue
                if c2.tag != tag:
                    res.recusados["na reconferência: mudou de tag"] += 1
                    continue
                c2.reconferido = True
                c = c2
                motivo = motivo_nao_cabe(c, aceitos, f)
                if motivo:
                    res.recusados[motivo] += 1
                    continue
            motivo, c.selo = _repeticao(c, banco, agora, f)  # com o preco ja reconferido
            if motivo:
                res.recusados[motivo] += 1
                continue
            link = _link(c, tag, cliente, banco, cfg, agora, res.erros, log)
            if not (link and link.lower().startswith("https://")):
                res.recusados["sem link de afiliado"] += 1
                continue
            if verificador is not None:
                # o link precisa ABRIR o produto certo na Shopee antes de ir para a tela
                try:
                    estado, detalhe = verificador(link, c.oferta.item_id)
                except Exception as e:  # noqa: BLE001 - defeito na conferencia tira o selo, nao derruba a rodada
                    estado, detalhe = "sem_resposta", f"falha ao conferir: {type(e).__name__}"
                if estado == "sem_resposta":
                    res.links_sem_conferencia += 1
                if estado == "quebrado":
                    res.recusados["link não abre o produto na Shopee"] += 1
                    res.erros.append(f"link {c.oferta.item_id}: {detalhe}")
                    log(f"  ! link {c.oferta.item_id} quebrado: {detalhe}")
                    continue
                c.link_conferido = estado == "ok"  # selo so quando a pagina final e a do produto certo
            c.link = link
            aceitos.append(c)
    return escolhidos

def _copiar(arquivos: dict, destino: Path, avisos: list, log: Callable) -> bool:
    """Copia as saidas; False se alguma falhou (ex.: ofertas.csv aberto no Excel)."""
    try:
        destino.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        avisos.append(f"não consegui criar {destino}: {e}")
        return False
    tudo = True
    for p in arquivos.values():
        try:
            shutil.copy2(p, destino / p.name)
        except OSError as e:
            tudo = False
            msg = f"não atualizei {destino / p.name} (arquivo aberto?): {e.strerror or e}"
            avisos.append(msg)
            log(f"  ! {msg}")
    return tudo


def recuperar_ultima(ultima: Path):
    """Se uma rodada morreu entre os dois renames, devolve a `ultima` anterior."""
    velha = ultima.with_name(ultima.name + ".velha")
    if not ultima.exists() and velha.exists():
        try:
            velha.rename(ultima)
        except OSError:
            pass


def _trocar_ultima(arquivos: dict, ultima: Path, avisos: list, log: Callable) -> bool:
    """Troca a pasta `ultima` inteira de uma vez (nunca mistura HTML novo com CSV velho).
    Se o Windows nao deixar (arquivo aberto no Excel), cai na copia arquivo a arquivo e
    avisa que ficou parcial."""
    nova = ultima.with_name(ultima.name + ".nova")
    velha = ultima.with_name(ultima.name + ".velha")
    recuperar_ultima(ultima)
    try:
        shutil.rmtree(nova, ignore_errors=True)
        shutil.rmtree(velha, ignore_errors=True)
        nova.mkdir(parents=True)
        for p in arquivos.values():
            shutil.copy2(p, nova / p.name)
        if ultima.exists():
            ultima.rename(velha)
        try:
            nova.rename(ultima)
        except OSError:
            if velha.exists() and not ultima.exists():
                velha.rename(ultima)  # desfaz: a anterior volta inteira
            raise
        shutil.rmtree(velha, ignore_errors=True)
        return True
    except OSError:
        shutil.rmtree(nova, ignore_errors=True)
        return _copiar(arquivos, ultima, avisos, log)


def rodar(cliente, banco: Banco, cfg: dict, pasta_saida: Path, agora: float | None = None,
          log: Callable = print, verificador: Callable | None = None) -> Resultado:
    """verificador(link, item_id) -> (estado, detalhe): confere se cada link abre o produto
    (robo.links). None = nao confere (demo e testes, sem internet)."""
    agora = time.time() if agora is None else agora
    res = Resultado()
    recuperar_ultima(Path(pasta_saida) / "ultima")  # antes de qualquer coisa que possa falhar
    id_exec = banco.abrir_execucao(agora)
    try:
        log("Coletando ofertas na Shopee...")
        ofertas, origens, res.erros = coletar(cliente, banco, cfg, agora, log)
        res.lidas = len(ofertas)
        candidatos = julgar(ofertas, origens, banco, cfg, agora)
        for c in candidatos:
            if not c.aprovado:
                res.recusados[c.recusa] += 1
        f = cfg["filtros"]
        regras = RegrasPreco.de_dict(cfg.get("regras_preco"))
        aceitar = bool(f.get("aceitar_sem_historico", True))

        def rejulgar(o: Oferta, origens: set) -> Candidato:
            hist = historico_para_julgar(banco, o, agora, regras.janela_dias)
            v = avaliar(o.preco_min, hist, agora, regras, aceitar, atual_max=o.preco_max)
            return avaliar_candidato(o, v, cfg, origens)

        log("Reconferindo preços e gerando links...")
        if verificador is not None:
            log("Conferindo se cada link abre o produto certo...")
        res.escolhidos = preencher(filas_por_tag(candidatos), cliente, banco, cfg, agora, res, rejulgar, log,
                                   verificador)
        todos = [c for lista in res.escolhidos.values() for c in lista]
        res.top = sorted(todos, key=lambda c: -c.pontos)[:int(f.get("top_do_dia", 10))]
        dias_hist = float(cfg["coleta"].get("manter_historico_dias", 120))
        banco.limpar_antigos(agora - dias_hist * DIA)

        quando = datetime.fromtimestamp(agora)
        resumo = {"lidas": res.lidas, "produtos_no_banco": banco.resumo()["produtos"]}
        pasta = Path(pasta_saida) / quando.strftime("%Y-%m-%d_%H%M%S")
        res.arquivos = salvar_saidas(pasta, res.escolhidos, res.recusados, cfg, quando, resumo, res.top)
        # so agora a memoria registra: o que nao chegou a vitrine nao conta como sugerido
        for tag, lista in res.escolhidos.items():
            for c in lista:
                banco.registrar_sugestao(c.oferta.item_id, agora, c.oferta.preco_min, tag)
        banco.commit()
        if not _trocar_ultima(res.arquivos, Path(pasta_saida) / "ultima", res.avisos, log):
            res.saida_parcial = True
        for extra in cfg["coleta"].get("copiar_para") or []:
            _copiar(res.arquivos, Path(extra), res.avisos, log)
        return res
    finally:
        res.chamadas = getattr(cliente, "chamadas", 0)
        banco.fechar_execucao(id_exec, time.time(), res.chamadas, res.lidas,
                              res.total_escolhidos, res.erros + res.avisos)
