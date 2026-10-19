"""Testes do robo. Tudo FICTICIO e offline: py -3.12 -m unittest discover -s tests
Os testes marcados [auditoria] reproduzem achados do Codex e dos 4 analistas (17/10/2026)."""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import sys
import tempfile
import unicodedata
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from robo.banco import Banco, RodadaEmAndamento, Trava  # noqa: E402
from robo.config import ler_nicho  # noqa: E402
from robo.curadoria import (avaliar_candidato, classificar, normalizar,  # noqa: E402
                            selecionar, verificar_bloqueio)
import robo.pipeline as pipeline_mod  # noqa: E402
from robo.pipeline import ErroColeta, montar_subids, rodar  # noqa: E402
from robo.precos import DIA, RegrasPreco, Veredito, avaliar  # noqa: E402
from robo.shopee_api import ClienteShopee, ErroShopee, Oferta, assinar  # noqa: E402
from robo.texto import AVISO_TOPO, legenda, milhar, nome_curto, reais  # noqa: E402
from robo.vitrine import celula_segura, gerar_html, salvar_saidas, url_segura  # noqa: E402

CFG = ler_nicho()
AGORA = 1_800_000_000.0  # 15/01/2027 05:00 (Brasilia)


def oferta(**kw) -> Oferta:
    base = dict(item_id=1, shop_id=10, nome="Kit Potes Herméticos Cozinha 10 peças", loja="Loja Teste",
                preco_min=50.0, preco_max=50.0, desconto=40, vendas=1000, nota=4.8, comissao=0.08,
                imagem="https://cf.shopee.com.br/file/x", link_produto="https://shopee.com.br/p-i.1.1",
                link_oferta="https://s.shopee.com.br/abc")
    base.update(kw)
    return Oferta(**base)


V_OK = Veredito("menor_preco", "Menor preço em 20 dias", True, 80.0, 0.375, False, 20, 4)
V_SEM = Veredito("sem_historico", "Sem histórico suficiente: desconto a confirmar", True)


def h(*pares):
    """(dias_atras, preco[, preco_max]) -> historico"""
    return [(AGORA - p[0] * DIA, *p[1:]) for p in pares]


# ----------------------------------------------------------------- API
class FakeTransporte:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def __call__(self, url, corpo, headers, timeout):
        self.pedidos.append((url, corpo, headers))
        r = self.respostas.pop(0)
        if isinstance(r, BaseException):
            raise r
        if isinstance(r, tuple):  # (status, bytes)
            return r
        return 200, json.dumps(r).encode()


def cliente(respostas, relogio=lambda: AGORA):
    t = FakeTransporte(respostas)
    c = ClienteShopee("123456", "segredo-teste", transporte=t, relogio=relogio,
                      dormir=lambda s: None, intervalo=0)
    return c, t


VAZIO = {"data": {"productOfferV2": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}


class TestAssinatura(unittest.TestCase):
    def test_formula(self):
        esperado = hashlib.sha256(b'1231700000000{"query":"x"}abc').hexdigest()
        self.assertEqual(assinar("123", "abc", 1700000000, '{"query":"x"}'), esperado)

    def test_header_assina_o_corpo_exato(self):
        c, t = cliente([VAZIO])
        c.buscar_ofertas(keyword='panela "inox"')
        _, corpo, headers = t.pedidos[0]
        ts = int(AGORA)
        sig = hashlib.sha256(f"123456{ts}".encode() + corpo + b"segredo-teste").hexdigest()
        self.assertEqual(headers["Authorization"],
                         f"SHA256 Credential=123456, Timestamp={ts}, Signature={sig}")
        self.assertIn("RoboAchadinhos", headers["User-Agent"])
        q = json.loads(corpo)["query"]
        self.assertIn('keyword: "panela \\"inox\\""', q)  # aspas escapadas, sem injecao

    def test_busca_por_item_para_reconferir(self):
        c, t = cliente([VAZIO])
        c.buscar_ofertas(item_id=55, shop_id=9, limit=1)
        q = json.loads(t.pedidos[0][1])["query"]
        self.assertIn("itemId: 55", q)
        self.assertIn("shopId: 9", q)

    def test_segredo_nao_vaza(self):
        c, _ = cliente([])
        self.assertNotIn("segredo", repr(c))

    def test_segredo_redigido_em_mensagem_de_erro(self):
        c, _ = cliente([{"errors": [{"message": "bad segredo-teste", "extensions": {"code": 10020}}]}])
        with self.assertRaises(ErroShopee) as ctx:
            c.buscar_ofertas(keyword="x")
        self.assertNotIn("segredo-teste", str(ctx.exception))


class TestErros(unittest.TestCase):
    def test_limite_tenta_de_novo(self):
        c, t = cliente([
            {"errors": [{"message": "x", "extensions": {"code": 10030, "message": "Rate limit"}}]},
            {"data": {"generateShortLink": {"shortLink": "https://s.shopee.com.br/ok"}}},
        ])
        self.assertEqual(c.link_curto("https://shopee.com.br/p"), "https://s.shopee.com.br/ok")
        self.assertEqual(len(t.pedidos), 2)

    def test_system_error_10000_tenta_de_novo(self):  # [auditoria]
        c, t = cliente([{"errors": [{"message": "x", "extensions": {"code": 10000}}]}, VAZIO])
        c.buscar_ofertas(keyword="x")
        self.assertEqual(len(t.pedidos), 2)

    def test_autenticacao_nao_insiste(self):
        c, t = cliente([{"errors": [{"message": "x", "extensions": {"code": 10020, "message": "Invalid Signature"}}]}])
        with self.assertRaises(ErroShopee) as ctx:
            c.link_curto("https://shopee.com.br/p")
        self.assertEqual(ctx.exception.codigo, 10020)
        self.assertIn("relogio", str(ctx.exception))
        self.assertEqual(len(t.pedidos), 1)

    def test_403_html_nao_insiste_e_e_fatal(self):  # [auditoria]
        c, t = cliente([(403, b"<html>Forbidden</html>")])
        with self.assertRaises(ErroShopee) as ctx:
            c.buscar_ofertas(keyword="x")
        self.assertEqual(ctx.exception.codigo, 10031)
        self.assertEqual(len(t.pedidos), 1)

    def test_502_html_tenta_de_novo(self):
        c, t = cliente([(502, b"<html>Bad gateway</html>"), VAZIO])
        c.buscar_ofertas(keyword="x")
        self.assertEqual(len(t.pedidos), 2)

    def test_incomplete_read_vira_erro_tratado(self):  # [auditoria]
        c, t = cliente([http.client.IncompleteRead(b"x")] * 4)
        with self.assertRaises(ErroShopee) as ctx:
            c.buscar_ofertas(keyword="x")
        self.assertIsNone(ctx.exception.codigo)

    def test_status_http_decide_mesmo_com_json(self):  # [auditoria] 2a rodada
        c, t = cliente([(401, b"{}")])
        with self.assertRaises(ErroShopee) as ctx:
            c.buscar_ofertas(keyword="x")
        self.assertEqual(ctx.exception.codigo, 10031)
        c, t = cliente([(429, b"{}"), VAZIO])
        c.buscar_ofertas(keyword="x")
        self.assertEqual(len(t.pedidos), 2)

    def test_erro_graphql_sem_codigo_nao_e_temporario(self):
        c, t = cliente([{"errors": [{"message": "Cannot query field foo"}]}])
        with self.assertRaises(ErroShopee):
            c.buscar_ofertas(keyword="x")
        self.assertEqual(len(t.pedidos), 1)


class TestParse(unittest.TestCase):
    def test_no_com_strings(self):
        o = Oferta.de_no({"itemId": "987", "shopId": 5, "productName": " Mop ", "priceMin": "79.90",
                          "priceMax": "89.9", "priceDiscountRate": 38, "sales": 8100, "ratingStar": "4.8",
                          "commissionRate": "0.08", "offerLink": "https://s.shopee.com.br/a"})
        self.assertEqual((o.item_id, o.nome, o.preco_min, o.preco_max, o.nota, o.comissao),
                         (987, "Mop", 79.9, 89.9, 4.8, 0.08))
        self.assertAlmostEqual(o.preco_de_estimado, 128.87, places=2)

    def test_comissao_fracao_documentada(self):
        o = Oferta.de_no({"itemId": 1, "priceMin": "10", "commissionRate": "0.0850"})
        self.assertAlmostEqual(o.comissao, 0.085)

    def test_no_invalido_descartado(self):
        self.assertIsNone(Oferta.de_no({"itemId": 1, "priceMin": "0"}))
        self.assertIsNone(Oferta.de_no({"priceMin": "10"}))

    def test_no_estranho_nao_derruba_pagina(self):  # [auditoria]
        c, _ = cliente([{"data": {"productOfferV2": {"nodes": [
            {"itemId": 1, "priceMin": "10", "shopId": "abc"},
            {"itemId": "x1", "priceMin": "10"},
            "lixo",
            {"itemId": 2, "priceMin": "20", "shopType": 1, "periodEndTime": "1.7e9"},
        ], "pageInfo": {"hasNextPage": False}}}}])
        ofertas, _ = c.buscar_ofertas(keyword="x")
        self.assertEqual([o.item_id for o in ofertas], [1, 2])  # shopId ruim so fica vazio
        self.assertIsNone(ofertas[0].shop_id)
        self.assertEqual(ofertas[1].shop_type, [1])
        self.assertEqual(ofertas[1].periodo_fim, 1_700_000_000)


# ----------------------------------------------------------------- preco
class TestPrecos(unittest.TestCase):
    def test_sem_historico(self):
        v = avaliar(50, h((1, 80)), AGORA)
        self.assertEqual(v.status, "sem_historico")
        self.assertTrue(v.aceito)
        self.assertFalse(avaliar(50, [], AGORA, aceitar_sem_historico=False).aceito)

    def test_preco_constante_e_preco_de_sempre(self):
        v = avaliar(189.9, h((25, 189.9), (15, 190), (6, 189.9)), AGORA)
        self.assertEqual(v.status, "preco_de_sempre")
        self.assertFalse(v.aceito)

    def test_queda_pequena_rejeitada(self):
        v = avaliar(95, h((20, 100), (13, 100), (6, 101)), AGORA)
        self.assertFalse(v.aceito)

    def test_codex_inflou_e_voltou(self):  # [auditoria] 100,100 -> 150,150,150 -> 100
        v = avaliar(100, h((25, 100), (20, 100), (6, 150), (4, 150), (2, 150)), AGORA)
        self.assertEqual(v.status, "subiu_antes")
        self.assertFalse(v.aceito)

    def test_codex_promocao_continuada_aceita(self):  # [auditoria] 3x100 depois 4x60, segue 60
        v = avaliar(60, h((12, 100), (10, 100), (8, 100), (4, 60), (3, 60), (2, 60), (1, 60)), AGORA)
        self.assertTrue(v.aceito, v.rotulo)
        self.assertAlmostEqual(v.queda_real, 0.40, places=2)
        self.assertEqual(v.dias_em_promocao, 4)

    def test_codex_tres_leituras_numa_hora_nao_sao_historico(self):  # [auditoria]
        hist = [(AGORA - 20 * DIA + s, 100) for s in (0, 1200, 2400)]
        self.assertEqual(avaliar(60, hist, AGORA).status, "sem_historico")

    def test_inflacao_longa_rejeitada(self):  # [auditoria] 50 por 14 dias, 90 por 16, volta a 50
        hist = h(*[(d, 50) for d in range(30, 16, -1)], *[(d, 90) for d in range(16, 0, -1)])
        v = avaliar(50, hist, AGORA)
        self.assertFalse(v.aceito, v.rotulo)

    def test_comecando_no_meio_da_inflacao(self):  # [auditoria] 3 dias a 90 e depois 50
        v = avaliar(50, h((3, 90), (2, 90), (1, 90)), AGORA)
        self.assertEqual(v.status, "sem_historico")

    def test_gangorra_semanal(self):  # [auditoria] 4 dias a 100, 3 a 60, repetindo
        hist = []
        for semana in range(4):
            for d in range(7):
                dias_atras = 28 - semana * 7 - d
                if dias_atras <= 0:
                    continue
                hist.append((dias_atras, 100 if d < 4 else 60))
        v = avaliar(60, h(*hist), AGORA)
        self.assertEqual(v.status, "preco_recorrente")
        self.assertFalse(v.aceito)

    def test_variacao_isca(self):  # [auditoria] so a variacao barata caiu
        hist = h(*[(d, 39.9, 39.9) for d in range(20, 0, -1)])
        v = avaliar(19.9, hist, AGORA, atual_max=39.9)
        self.assertEqual(v.status, "variacao_isca")
        self.assertFalse(v.aceito)

    def test_relampago_real(self):
        v = avaliar(59, h((20, 100), (13, 100), (6, 99), (1, 100)), AGORA)
        self.assertEqual(v.status, "menor_preco")
        self.assertTrue(v.queda_brusca)

    def test_promocao_longa_continua_valendo(self):  # [auditoria] 18 dias a 60 depois de 100
        hist = h(*[(d, 100) for d in range(29, 18, -1)], *[(d, 60) for d in range(18, 0, -1)])
        v = avaliar(60, hist, AGORA)
        self.assertTrue(v.aceito, v.rotulo)
        self.assertEqual(v.dias_em_promocao, 18)

    def test_varias_leituras_no_dia_nao_pesam_mais(self):
        hist = h((20, 100), (13, 100), (6, 100)) + [(AGORA - 1 * DIA + s, 60) for s in range(0, 3600, 300)]
        v = avaliar(60, hist, AGORA)
        self.assertEqual(v.preco_normal, 100)

    def test_queda_real_sem_ser_minimo(self):
        v = avaliar(70, h((25, 100), (18, 100), (12, 65), (6, 100), (1, 100)), AGORA)
        self.assertEqual(v.status, "queda_real")

    # --- 2a rodada do Codex
    def test_codex2_inflacao_longa_e_reducao_pequena(self):  # [auditoria] 100,100 / 150 x27 / 96
        hist = h((29, 100), (28, 100), *[(d, 150) for d in range(27, 0, -1)])
        v = avaliar(96, hist, AGORA)
        self.assertFalse(v.aceito, v.rotulo)

    def test_codex2_promocao_que_melhora_continua_aceita(self):  # [auditoria] 100 x3 / 60 x10 / 55
        hist = h((20, 100), (15, 100), (12, 100), *[(d, 60) for d in range(10, 0, -1)])
        v = avaliar(55, hist, AGORA)
        self.assertTrue(v.aceito, v.rotulo)
        self.assertEqual(v.preco_normal, 100)
        self.assertEqual(v.status, "menor_preco")

    def test_codex2_menor_preco_considera_a_promocao(self):  # [auditoria] ontem 60, hoje 70
        v = avaliar(70, h((20, 100), (13, 100), (8, 100), (2, 60), (1, 60)), AGORA)
        self.assertNotEqual(v.status, "menor_preco")
        self.assertNotIn("Menor", v.rotulo)

    def test_codex2_cobertura_entre_as_leituras(self):  # [auditoria] D-20, D-19, D-18
        v = avaliar(60, h((20, 100), (19, 100), (18, 100)), AGORA)
        self.assertEqual(v.status, "sem_historico")

    # --- 3a rodada do Codex
    def test_codex3_precos_antigos_variados_nao_escapam(self):  # [auditoria] 100,104,108 / 150 x26 / 100
        hist = h((29, 100), (28, 104), (27, 108), *[(d, 150) for d in range(26, 0, -1)])
        v = avaliar(100, hist, AGORA)
        self.assertFalse(v.aceito, v.rotulo)

    def test_codex3_menor_preco_ve_leitura_dentro_do_dia(self):  # [auditoria] ontem 60,100,100
        hist = h((20, 100), (13, 100), (6, 100)) + [(AGORA - DIA + s, p) for s, p in ((0, 60), (3600, 100), (7200, 100))]
        v = avaliar(70, hist, AGORA)
        self.assertNotEqual(v.status, "menor_preco")

    def test_codex3_corte_com_referencia_suficiente(self):  # [auditoria] 100 x3 seguidos / 80 x3 / 50
        v = avaliar(50, h((20, 100), (19, 100), (18, 100), (12, 80), (8, 80), (4, 80)), AGORA)
        self.assertTrue(v.aceito, v.rotulo)

    def test_relampago_de_um_dia_nao_rebaixa_referencia(self):
        v = avaliar(59, h((25, 100), (18, 100), (12, 60), (6, 100), (2, 100)), AGORA)
        self.assertEqual(v.preco_normal, 100)
        self.assertTrue(v.aceito)

    # --- 4a rodada do Codex
    def test_codex4_gangorra_diaria(self):  # [auditoria] 100 nos dias impares, 60 nos pares
        v = avaliar(60, h(*[(d, 100 if d % 2 else 60) for d in range(29, 0, -1)]), AGORA)
        self.assertFalse(v.aceito, v.rotulo)

    def test_codex4_dois_relampagos_de_um_dia_rebaixam(self):
        v = avaliar(60, h((25, 100), (20, 60), (14, 100), (9, 61), (4, 100)), AGORA)
        self.assertFalse(v.aceito, v.rotulo)

    def test_historico_fora_da_janela_ignorado(self):
        v = avaliar(50, h((60, 100), (45, 100), (40, 100)), AGORA, RegrasPreco(janela_dias=30))
        self.assertEqual(v.status, "sem_historico")


# ----------------------------------------------------------------- curadoria
class TestCuradoria(unittest.TestCase):
    def tag(self, nome, origens=None):
        return classificar(nome, CFG["tags"], origens, CFG.get("excluir_global"))[0]

    def test_normalizar(self):
        self.assertEqual(normalizar("Panela  Pressão-Inox!"), "panela pressao inox")

    def test_titulos_realistas(self):  # [auditoria] erros apontados pelo analista de curadoria
        casos = {
            "Almofada de Amamentação Ergonômica": "maternidade",
            "Jogo de Panelas Antiaderente 5 Peças": "cozinha",
            "Conjunto de Panelas Inox": "cozinha",
            "Bolsa Térmica Marmita Fitness": "cozinha",
            "Base Box Cama Casal": "casa",
            "Saia para Cama Box Queen": "casa",
            "Body Splash Feminino 200ml": "feminino",
            "Body Canelado Blogueira Feminino": "feminino",
            "Kit 5 Bodies Bebê Manga Curta": "bebe",
            "Sutiã sem Bojo Renda": "feminino",
            "Calcinha Fio Dental Kit 5": "feminino",
            "Mop Giratório 360 com Balde": "limpeza",
            "Lixeira Cozinha Inox 5L": "cozinha",
            "Escova de Cabelo Raquete": "feminino",
            "Mandoline Fatiador Legumes": "cozinha",
        }
        erros = {n: (self.tag(n), esperado) for n, esperado in casos.items() if self.tag(n) != esperado}
        self.assertEqual(erros, {})

    def test_fora_do_nicho_mesmo_vindo_da_busca(self):  # [auditoria]
        for nome in ("Relógio moderno", "Carregador USB-C Turbo", "Chave de fenda kit"):
            self.assertIsNone(self.tag(nome, {"casa"}), nome)

    def test_exclusao_global(self):  # [auditoria]
        self.assertIsNone(self.tag("Aspirador Automotivo Portátil"))
        self.assertIsNone(self.tag("Tapete Higiênico Pet"))

    def test_origem_desempata(self):
        self.assertEqual(self.tag("Organizador Feminino", {"casa"}), "casa")  # empate 1x1
        self.assertEqual(self.tag("Organizador Feminino", {"feminino"}), "feminino")

    def test_palavra_inteira(self):
        self.assertIsNone(self.tag("Relogio moderno"))  # "rn" nao casa dentro de "moderno"

    def test_bloqueios_nbcal(self):  # [auditoria]
        b, comb = CFG["bloqueios"], CFG["bloqueios_combinados"]
        for nome in ("Kit Mamadeira Anticólica", "Chupeta Ortodôntica Silicone", "Kit Chuquinha 3 peças",
                     "Bico Ortodôntico Tam 2", "Leite em Pó Ninho Fases 1+ 800g", "Aptamil Profutura 2",
                     "Bico de Silicone para Bebê", "Bico latex tamanho 1", "Papinha Orgânica Kit 6"):
            self.assertIn("NBCAL", verificar_bloqueio(nome, b, comb) or "", nome)

    def test_nao_bloqueia_bico_de_pato_de_cabelo(self):
        self.assertIsNone(verificar_bloqueio("Presilha Bico de Pato Cabelo Kit 12",
                                             CFG["bloqueios"], CFG["bloqueios_combinados"]))

    def test_bloqueio_falsificacao_e_pilha(self):
        b = CFG["bloqueios"]
        self.assertIn("falsificação", verificar_bloqueio("Bolsa Réplica Primeira Linha", b))
        self.assertIn("falsificação", verificar_bloqueio("Perfume Contratipo 100ml", b))
        self.assertIsNone(verificar_bloqueio("Pilha AAA recarregável", b))

    def test_aviso_kit_e_sono_seguro(self):
        c = avaliar_candidato(oferta(nome="Kit Higiene Bebê 5 peças"), V_OK, CFG)
        self.assertIn("NBCAL", c.aviso)
        c = avaliar_candidato(oferta(nome="Ninho Redutor Bebê"), V_OK, CFG)
        self.assertIn("sono seguro", c.aviso)

    def test_filtros(self):
        ok = avaliar_candidato(oferta(), V_OK, CFG)
        self.assertTrue(ok.aprovado, ok.recusa)
        self.assertEqual(ok.tag, "cozinha")
        self.assertIn("desconto", avaliar_candidato(oferta(desconto=20), V_SEM, CFG).recusa)
        self.assertIn("nota", avaliar_candidato(oferta(nota=4.5), V_OK, CFG).recusa)
        self.assertIn("nota", avaliar_candidato(oferta(nota=None), V_OK, CFG).recusa)
        self.assertIn("vendas", avaliar_candidato(oferta(vendas=30), V_OK, CFG).recusa)
        self.assertIn("comissão", avaliar_candidato(oferta(comissao=0.01), V_OK, CFG).recusa)
        self.assertIn("faixa", avaliar_candidato(oferta(preco_min=749.0, preco_max=749.0), V_OK, CFG).recusa)
        ruim = Veredito("preco_de_sempre", "Preço de sempre", False, 50, 0.0)
        self.assertEqual(avaliar_candidato(oferta(), ruim, CFG).recusa, "Preço de sempre")

    def test_com_historico_vale_a_queda_real(self):  # [auditoria] -60% anunciado, queda real 11%
        pouca = Veredito("queda_real", "11% abaixo", True, 100, 0.11)
        c = avaliar_candidato(oferta(desconto=60), pouca, CFG)
        self.assertIn("queda real", c.recusa)
        # Shopee diz -20%, mas o historico prova 37,5%: entra
        self.assertTrue(avaliar_candidato(oferta(desconto=20), V_OK, CFG).aprovado)

    def test_desconto_falso_sem_historico_nao_vence_queda_real(self):  # [auditoria]
        falso = avaliar_candidato(oferta(desconto=80, comissao=0.03), V_SEM, CFG).pontos
        real = avaliar_candidato(oferta(desconto=35, comissao=0.12), V_OK, CFG).pontos
        self.assertGreater(real, falso)

    def test_limite_por_loja_isolado(self):  # [auditoria] nomes bem diferentes, mesma loja
        nomes = ["Garrafa Térmica Inox 1L", "Tábua de Corte Bambu", "Jogo de Facas Chef",
                 "Escorredor de Louça Aço"]
        cs = [avaliar_candidato(oferta(item_id=i, nome=n), V_OK, CFG) for i, n in enumerate(nomes)]
        sel = selecionar(cs, CFG["filtros"])["cozinha"]
        self.assertEqual(len(sel), CFG["filtros"]["max_por_loja_por_tag"])

    def test_duplicado_por_similaridade(self):
        cs = [avaliar_candidato(oferta(item_id=i, shop_id=i, nome=f"Kit Potes Herméticos Cozinha {i} peças"),
                                V_OK, CFG) for i in range(4)]
        self.assertEqual(len(selecionar(cs, CFG["filtros"])["cozinha"]), 1)

    def test_teto_de_sem_historico_por_tag(self):
        nomes = ["Garrafa Térmica", "Tábua de Corte", "Jogo de Facas", "Escorredor de Louça",
                 "Porta Tempero Giratório", "Assadeira Retangular"]
        cs = [avaliar_candidato(oferta(item_id=i, shop_id=i, nome=n), V_SEM, CFG) for i, n in enumerate(nomes)]
        fila = selecionar(cs, CFG["filtros"])["cozinha"]
        self.assertEqual(len(fila), CFG["filtros"]["max_sem_historico_por_tag"])


# ----------------------------------------------------------------- texto/saidas
class TestTexto(unittest.TestCase):
    _UNIDADES = {"pecas", "peças", "unidades", "un", "lugares", "meses", "anos", "horas", "ml", "cm", "m", "w",
                 "x", "em", "a", "de", "partir", "por", "pcs", "peca", "peça", "andares", "queimadores", "pares",
                 "conserva"}
    _EXTENSO = {"um", "uma", "dois", "duas", "tres", "três", "quatro", "cinco", "seis", "dez", "doze"}

    def assert_legit(self, titulo):
        """25a rodada: o nome da legenda nao tem NENHUM numero do vendedor; as palavras comuns
        do titulo (fora numero, unidade e conector que so existem por causa dele) continuam."""
        from robo.texto import _ESPECIFICACAO, _TEMPO, _no_vocabulario
        unidades = self._UNIDADES | set(_ESPECIFICACAO) | set(_TEMPO) | {"litro", "polegada", "ano"}
        r = nome_curto(titulo)
        self.assertIsNone(re.search(r"\d|%|\$", r), (titulo, r))
        esperadas, anterior_num = [], False
        for w in titulo.split():
            baixo = w.lower().strip(".,")
            if re.search(r"\d", w) or baixo in self._EXTENSO:
                anterior_num = True
                continue
            if anterior_num and baixo in unidades:
                continue
            anterior_num = False
            if baixo in self._UNIDADES or not _no_vocabulario(w.strip(".,")):
                continue  # 27a rodada: so palavra do vocabulario permitido vai para a legenda
            esperadas.append(w)
        if len(esperadas) < 2:
            self.assertEqual(r, "Produto", (titulo, r))  # sobrou uma palavra so: nome generico
            return
        for w in esperadas:
            self.assertIn(w, r.split(), (titulo, r, w))
    def test_reais(self):
        self.assertEqual(reais(1234.5), "R$ 1.234,50")
        self.assertEqual(reais(9.9), "R$ 9,90")

    def test_milhar(self):
        self.assertEqual(milhar(3400), "3,4 mil")
        self.assertEqual(milhar(10000), "10 mil")
        self.assertEqual(milhar(950), "950")

    def test_nome_curto_tira_ruido(self):
        self.assertEqual(nome_curto("Mop Giratório [Envio Imediato] Frete Grátis"), "Mop Giratório")
        self.assertTrue(len(nome_curto("palavra " * 30)) <= 71)

    def test_codex7_titulo_nao_leva_alegacao_do_vendedor(self):  # [auditoria] 7a rodada
        for titulo in ("Kit Potes Herméticos Cozinha 70% OFF", "Kit Potes Herméticos -60% Cozinha",
                       "Kit Potes Herméticos Desconto 50% Cozinha", "Kit Potes Herméticos Por R$ 19,90",
                       "Kit Potes Herméticos MENOR PREÇO Black Friday", "Kit Potes Herméticos Até 80% Off",
                       "Kit Potes Herméticos Oferta Relâmpago Cupom"):
            limpo = nome_curto(titulo)
            self.assertNotIn("%", limpo, titulo)
            self.assertNotIn("R$", limpo, titulo)
            for palavra in ("off", "desconto", "menor", "black", "relâmpago", "cupom"):
                self.assertNotIn(palavra, limpo.lower(), titulo)
            self.assertIn("Potes Herméticos", limpo)
        c = avaliar_candidato(oferta(nome="Kit Potes Herméticos Cozinha 70% OFF"), V_OK, CFG)
        c.link = "https://s.shopee.com.br/abc"
        t = legenda(c)
        self.assertNotIn("70%", t)
        self.assertIn("38% abaixo do preço normal", t)
        self.assertEqual(nome_curto("70% OFF"), "Produto")

    def test_codex8_alegacoes_sem_palavra_chave_conhecida(self):  # [auditoria] 8a rodada
        casos = {
            "Kit Potes Herméticos pela metade do preço": "Kit Potes Herméticos",
            "Kit Potes Herméticos de 199,90 por 50,00": "Kit Potes Herméticos",
            "Kit Potes Herméticos Leve 3 Pague 2": "Kit Potes Herméticos",
            "Kit Potes Herméticos Ganhe Brinde": "Kit Potes Herméticos",
            "Kit Potes Herméticos Preço Baixo Imperdível": "Kit Potes Herméticos",
            "Cortina Blackout 2,80m x 1,80m Sala": "Cortina Blackout Sala",  # 25a: medida sai da legenda
            "Bateria 2,50mah Recarregável Kit": "Bateria Recarregável Kit",
        }
        for titulo, esperado in casos.items():
            self.assertEqual(nome_curto(titulo), esperado, titulo)

    def test_codex8_cupom_e_hashtag_so_sem_alegacao(self):  # [auditoria] 8a rodada
        from robo.texto import cupom_seguro, hashtag_segura
        self.assertEqual(cupom_seguro(" achado10 "), "ACHADO10")
        for ruim in ("GANHE70 - 70% OFF em tudo", "70%OFF", "AB"):
            with self.assertRaises(ValueError):
                cupom_seguro(ruim)
        self.assertEqual(hashtag_segura("#achadinhos"), "#achadinhos")
        for ruim in ("#70%OFF", "#MenorPreco", "#DescontoHoje", "achadinhos", "#a b"):
            with self.assertRaises(ValueError):
                hashtag_segura(ruim)
        c = avaliar_candidato(oferta(), V_OK, CFG)
        c.link = "https://s.shopee.com.br/abc"
        t = legenda(c, cupom="achado10")
        self.assertIn("Cupom ACHADO10 (confira valor, regras e validade no app)", t)

    def test_codex8_config_com_alegacao_e_recusado(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = json.loads((Path(__file__).resolve().parent.parent / "config" / "nicho.json").read_text(encoding="utf-8"))
            cfg["legenda"]["hashtags"] = ["#achadinhos", "#MenorPreco"]
            p = Path(tmp) / "nicho.json"
            p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                ler_nicho(p)

    def test_codex9_alegacao_por_extenso_e_radicais(self):  # [auditoria] 9a rodada
        casos = {
            "Kit Potes Herméticos Economize 70 por cento": "Kit Potes Herméticos",
            "Kit Potes Herméticos Aproveite Só Hoje": "Kit Potes Herméticos",
            "Kit Potes Herméticos 3x mais barato": "Kit Potes Herméticos",
            "Kit Potes Herméticos por apenas 49 reais": "Kit Potes Herméticos",
            "Kit Potes Herméticos Garanta o Seu": "Kit Potes Herméticos",
            "Mixer Offset Pro 500W": "Mixer Pro",
            "Kit 5 Bodies Bebê Algodão": "Kit Bodies Bebê Algodão",
        }
        for titulo, esperado in casos.items():
            self.assertEqual(nome_curto(titulo), esperado, titulo)

    def test_codex9_config_rigido(self):  # [auditoria] hashtags, nome de tag, emoji, rotulo
        from robo.texto import hashtag_segura, validar_textos_do_config
        for ruim in ("#GanheBrinde", "#Leve3Pague2", "#FreteGratis", "#Economize"):
            with self.assertRaises(ValueError):
                hashtag_segura(ruim)
        base = json.loads((Path(__file__).resolve().parent.parent / "config" / "nicho.json").read_text(encoding="utf-8"))
        validar_textos_do_config(base)  # o config real passa
        for mexe in (lambda c: c["tags"].__setitem__("MenorPreco", c["tags"].pop("cozinha")),
                     lambda c: c["tags"].__setitem__("menorpreco", c["tags"].pop("cozinha")),
                     lambda c: c["tags"]["cozinha"].__setitem__("emoji", "70% OFF"),
                     lambda c: c["tags"]["cozinha"].__setitem__("rotulo", "cozinha em promoção")):
            cfg = json.loads(json.dumps(base))
            mexe(cfg)
            with self.assertRaises(ValueError):
                validar_textos_do_config(cfg)

    def test_codex10_unicode_largura_cheia(self):  # [auditoria] 10a rodada
        from robo.texto import tem_alegacao, validar_textos_do_config
        self.assertEqual(nome_curto("Kit Potes Herméticos 70％"), "Kit Potes Herméticos")
        self.assertEqual(nome_curto("Kit Potes Herméticos ７０％ ＯＦＦ"), "Kit Potes Herméticos")
        self.assertTrue(tem_alegacao("Kit Potes 70％"))
        base = json.loads((Path(__file__).resolve().parent.parent / "config" / "nicho.json").read_text(encoding="utf-8"))
        for emoji in ("７０％", "７", "Ａ", "🍳7"):
            cfg = json.loads(json.dumps(base))
            cfg["tags"]["cozinha"]["emoji"] = emoji
            with self.assertRaises(ValueError, msg=emoji):
                validar_textos_do_config(cfg)

    def test_codex10_radical_em_qualquer_ocorrencia(self):  # [auditoria] 10a rodada
        self.assertEqual(nome_curto("Kit Potes Herméticos MegaEconomia Economize muito"),
                         "Kit Potes Herméticos")
        self.assert_legit("Fogão Cooktop 4 Queimadores Inox")
        self.assert_legit("Liquidificador Turbo 1200W")
        self.assert_legit("Panela Garantia 1 Ano Inox")
        self.assertEqual(nome_curto("Kit Potes Herméticos Oferta sensacional"), "Kit Potes Herméticos")
        self.assertEqual(nome_curto("Mop Giratório [Frete Grátis] Balde 360"), "Mop Giratório Balde")

    def test_codex11_menorpreco_colado_e_percentual_arabe(self):  # [auditoria] 11a rodada
        from robo.texto import tem_alegacao
        for titulo in ("Kit Potes Herméticos MenorPreco", "Kit Potes Herméticos MenorPreço",
                       "Kit Potes Herméticos 70٪", "Kit Potes Herméticos 70﹪ desconto",
                       "Kit Potes Herméticos 70‰", "Kit Potes Herméticos ＄19", "Kit Potes Herméticos €19",
                       "Kit Potes Herméticos uma oportunidade sensacional"):
            self.assertEqual(nome_curto(titulo), "Kit Potes Herméticos", titulo)
            self.assertTrue(tem_alegacao(titulo), titulo)
        self.assertFalse(tem_alegacao("Mixer Offset Pro 500W"))
        self.assertFalse(tem_alegacao("Fogão Cooktop 4 Queimadores Inox"))

    def test_codex12_radical_colado_com_sufixo(self):  # [auditoria] 12a rodada
        for titulo in ("Kit Potes Herméticos MenorPrecoGarantido", "Kit Potes Herméticos MenorPrecos",
                       "Kit Potes Herméticos SuperLiquidação", "Kit Potes Herméticos FreteGratis",
                       "Kit Potes Herméticos PelaMetade", "Kit Potes Herméticos BlackFridayJá",
                       "Kit Potes Herméticos CupomExtra", "Kit Potes Herméticos OfertaRelâmpago",
                       "Kit Potes Herméticos MenorPrecoComprovado", "Kit Potes Herméticos MenorPrecoConfirmado",
                       "Kit Potes Herméticos PrecoCerto", "Kit Potes Herméticos MenorPreçoCaiu"):
            self.assertEqual(nome_curto(titulo), "Kit Potes Herméticos", titulo)
        for legit in ("Liquidificador Turbo 1200W", "Panela Garantia 1 Ano Inox",
                      "Fogão Cooktop 4 Queimadores Inox", "Mixer Offset Pro 500W"):
            self.assert_legit(legit)

    def test_codex14_grafias_extenso_e_fragmentacao(self):  # [auditoria] 14a rodada
        for sufixo in ("70 por-cento", "70 p/ cento", "70 pct", "70 p.c.", "setenta por cento",
                       "vinte reais", "menor pr eço", "menor p r e ç o", "menor pre​ço",
                       "des-con-to", "Uma pechincha", "metade do valor"):
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        for legit in ("Kit 10 pcs Potes Herméticos", "Tinta Sempre Colorido Kit", "Foto Real Kit Potes Inox",
                      "Kit 3 Peças Potes Herméticos", "Escorredor Dois Andares Inox"):
            self.assert_legit(legit)

    def test_antecipacao_15_confusaveis_leet_idiomas_urgencia(self):
        for sufixo in ("70% оff",                 # o cirilico
                       "Desсonto Total",          # c cirilico
                       "d3sc0nt0 hoje", "pr0m0ç@o", "SALE", "Deal do Dia", "descuento", "rebajas",
                       "discount", "Outlet", "por só 19", "só 19 hoje", "Estoque Limitado",
                       "Últimas Unidades", "Baixou!", "Caiu", "de graça", "Free Shipping"):
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        for legit in ("Saleiro Inox Kit Potes", "Fone Bluetooth Hands Free", "Garrafa Térmica conserva por 12 horas",
                      "Brinquedo Educativo a partir de 3 anos", "Kit 10 pcs Potes Herméticos", "Mop 360 Microfibra Kit"):
            self.assert_legit(legit)

    def test_codex15_valores_unidades_fragmentos_pagamento(self):  # [auditoria] 15a rodada
        for sufixo in ("seiscentos reais", "setecentos reais", "oitocentos reais", "novecentos reais",
                       "VinteReais", "setentareais", "19 centavos", "19 pratas", "19 BRL", "BRL 19",
                       "USD 19", "19 euros", "70 percent", "70 per cent", "70 p c t", "70 p-c-t",
                       "19 r e a i s", "19 re-ais", "70 o f f", "70 0ff", "por 19 no Pix",
                       "a partir de 19 no Pix", "19,9 no Pix", "10x de 9", "à vista", "sem juros"):
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        from robo.texto import hashtag_segura
        for ruim in ("#VinteReais", "#SetentaReais", "#SetentaPorCento", "#Setenta_Por_Cento"):
            with self.assertRaises(ValueError, msg=ruim):
                hashtag_segura(ruim)
        for legit in ("Kit Potes Herméticos", "Brinco de Prata Folheado", "Cortina 2,80m Blackout",
                      "Garrafa 1,5 Litro Inox", "Brinquedo a partir de 3 anos", "Garrafa conserva por 12 horas",
                      "Mixer Offset 500W", "Couro Real Bolsa Feminina"):
            self.assert_legit(legit)
        hashtag_segura("#achadinhos")
        hashtag_segura("#shopee")

    def test_codex16_analisador_de_numeros(self):  # [auditoria] 16a rodada
        for sufixo in ("UmReal", "umreal", "VinteReal", "VintePrata", "VinteConto", "VinteDolar", "VinteDólares",
                       "19 EUR", "19 eur", "BRL vinte", "USD vinte", "EUR vinte",
                       "19 r e a l", "19 d o l a r", "19 p r a t a hoje", "19 c o n t o hoje", "19 dól ares",
                       "19 r3al", "19 pr4ta", "19 c0nt0", "19 d0lar", "70 p3rc3n7", "70 p/c", "70 p c",
                       "por 19 hoje", "por 19 cada", "por 19 a unidade", "por dezenove", "a partir de dezenove",
                       "19 no cartão", "19 em dinheiro", "19 em 2x", "19 em duas vezes", "19 no boleto",
                       "70 pontos percentuais"):
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        from robo.texto import hashtag_segura
        for ruim in ("#umreal", "#vintedólares", "#BRLVinte", "#USDVinte", "#EURVinte", "#PorDezenove",
                     "#APartirDeDezenove", "#pordezenove"):
            with self.assertRaises(ValueError, msg=ruim):
                hashtag_segura(ruim)
        for legit in ("Brinquedo Educativo a partir de 12 anos", "Tapete a partir de 20 cm", "Garrafa 1,50 Litro Inox",
                      "Kit 3 em 1 Organizador", "Escorredor Dois Andares Inox",
                      "Umidificador de Ar 300ml", "Cortina 2,80m x 1,80m Sala", "Mesa 50 x 70 cm Dobrável",
                      "Garrafa conserva por 12 horas", "Bolsa Feminina Uma Alça", "Kit 5 Bodies Bebê"):
            self.assert_legit(legit)

    def test_codex17_numero_so_fica_se_inofensivo(self):  # [auditoria] 17a rodada
        for sufixo in ("19r3al", "19pr4ta", "19c0nt0", "19d0lar", "70p3rc3n7", "70 p 3 r c 3 n 7",
                       "70 p o n t o s percentuais", "19 r@al", "por 19 em qualquer compra", "por 19 em ate 2x",
                       "19,90 em ate 2x", "19,90 un", "19 no credito", "19 no debito", "19 a prazo",
                       "vinte e um reais", "cento e vinte reais", "19 mil reais", "19 e 90 centavos",
                       "pordezenovehoje", "BRLvintehoje", "porvinteeum", "brlvinteeum", "19"):
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        from robo.texto import hashtag_segura
        for ruim in ("#pordezenovehoje", "#brlvintehoje", "#porvinteeum", "#brlvinteeum"):
            with self.assertRaises(ValueError, msg=ruim):
                hashtag_segura(ruim)
        for legit in ("Kit 5 Bodies Bebê Algodão", "Mesa 50x70cm Dobrável", "Bebê 0 a 12 meses Body",
                      "Kit 3 em 1 Organizador", "Porcelana Branca Kit Pratos", "Sofá Dois Lugares Retrátil",
                      "Garrafa 1,5L Inox Térmica", "Bateria 2,50mah Recarregável Kit", "Europa Mapa Decorativo Quadro"):
            self.assert_legit(legit)

    def test_codex18_pagamento_parcela_periodo_percentual_moeda_antes(self):  # [auditoria] 18a rodada
        for sufixo in ("19 credito", "19 debito", "19 cash", "19 via transferencia", "19 por unidade",
                       "19 por mes", "19 mensais", "2x19", "2x19 no credito", "2x19real", "2x19r3al", "2x19conto",
                       "2x19dolar", "19/mes", "19,90/mes", "70 pontos porcentuais", "70 pontos de percentual",
                       "70 pts percentuais", "reais dezenove hoje", "reais: 19 hoje"):
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        from robo.texto import hashtag_segura
        with self.assertRaises(ValueError):
            hashtag_segura("#reaisdezenovehoje")
        for legit in ("Couro Real 2 Peças Bolsa", "3 Unidades Kit", "Mesa 50x70cm Dobrável",
                      "Chave 1/2 polegada Kit", "Garrafa 12 meses de garantia"):
            self.assert_legit(legit)

    def test_codex19_periodicidade_barra_percentual_moeda(self):  # [auditoria] 19a rodada
        for sufixo in ("19 semanal", "19 anual", "19 quinzenais", "19 bimestrais", "19 trimestrais",
                       "19 semestrais", "19/2 meses", "19/30 dias", "19/duas semanas",
                       "70 pontos de per centual", "70 pontos de per-centual", "70 pontos de por centuais",
                       "70 pontos de p e r c e n t u a i s", "reais 19 un", "reais: 19 unidades", "euros 19 un",
                       "dólares 19 unidades", "reais dezenove unidades", "reais 19un", "real 19 hoje"):
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        self.assertEqual(nome_curto("Fotos Reais 3 Unidades Kit"), "Produto")  # ruido + numeros saem
        for legit in ("Couro Real 2 Peças Bolsa", "Chave 1/2 polegada Kit",
                      "Kit Chaves 3/4 Inox", "Garrafa 12 semanas de garantia", "Bebê 0 a 12 meses Body"):
            self.assert_legit(legit)

    def test_codex20_proximidade_fracao_excecoes(self):  # [auditoria] 20a rodada
        for sufixo in ("produto euros 19 hoje", "produto dólares 19 hoje", "produto centavos 19 hoje",
                       "produto reais: 19 un", "produto reais: 19un", "centavo 19 un", "re-ais 19 un",
                       "r e a i s 19 un", "eu-ros 19 un", "19/30 min", "19/30 minutos", "19/24 h", "19/60 seg",
                       "19/2 a 3 meses", "19/2 ou 3 meses", "19 quadrimestral", "19 quadrimestrais", "19 bienal",
                       "19 bienais", "19 bissemanal", "19 bissemanais", "percentual de 70 pontos",
                       "percentuais: 70 pontos", "per centual de 70 pontos"):
            self.assertIn(nome_curto("Kit Potes Herméticos " + sufixo),
                          ("Kit Potes Herméticos", "Kit Potes Herméticos produto"), sufixo)
        for legit in ("Kit Chaves 3/4 Inox", "Chave 1/2 polegada Kit", "Couro Real 2 Peças Bolsa", "Manual de Instruções Kit 3 Peças", "Boneca Realista 2 Roupas"):
            self.assert_legit(legit)

    def test_codex21_lista_unica_e_fragmentos(self):  # [auditoria] 21a rodada
        for sufixo in ("re-al 19 un", "r e a l 19 un", "r3al 19 un", "c enta vos 19 un", "d olare s 19 un",
                       "conto 19 hoje", "contos 19 hoje", "pila 19 hoje", "pilas 19 hoje", "GBP 19 hoje",
                       "19 GBP hoje", "ARS 19 hoje", "19 ARS hoje", "19/32 dias", "19/64 h", "1/2 meses",
                       "3/4 semanas", "1/2 a 3 meses", "1/2 ou 3 meses", "pct de 70 pontos", "p.c. de 70 pontos",
                       "p c t de 70 pontos", "diária 19 hoje", "diárias 19 hoje", "diariamente 19 hoje"):
            r = nome_curto("Kit Potes Herméticos " + sufixo)
            self.assertTrue(r == "Kit Potes Herméticos" or not re.search(r"\d", r), (sufixo, r))
            self.assertTrue(r.startswith("Kit Potes Herméticos"), (sufixo, r))
        for legit in ("Couro Real 2 Peças Bolsa", "Boneca Realista 2 Roupas", "Kit Chaves 3/4 Inox",
                      "Chave 1/2 polegada Kit"):
            self.assert_legit(legit)

    def test_codex22_colado_fracao_moedas(self):  # [auditoria] 22a rodada
        casos = ["r3al19", "re-al19", "r e a l19", "c enta vos19", "d olare s19", "conto19", "contos19", "pila19",
                 "pilas19", "centavo19", "contodezenove", "pilavinte", "diaria19", "diariadezenove",
                 "GBP19", "ARS19", "JPY19", "CNY19", "CAD19", "AUD19", "CHF19", "MXN19", "CLP19", "COP19", "PEN19",
                 "UYU19", "PYG19", "BOB19", "GBPdezenove", "ARSvinte",
                 "p.c. de setenta pontos", "p.c.: 70 pontos", "p.c. em 70 pontos", "p c de 70 pontos",
                 "pc de 70 pontos", "p/c de 70 pontos", "p-c de 70 pontos", "pct70 pontos", "pctsetenta pontos",
                 "por 1/2", "por 1/2 hoje", "a partir de 1/2", "custa 1/2", "1/2 cada mes", "19/32 por mes",
                 "19/32 d", "19/32 ds", "19/32 segs", "19/32 mins", "19/32 longos dias", "19/32 corridos dias",
                 "19/32 durante o mes", "19 pesos argentinos", "19 libras esterlinas", "19 ienes", "19 yuan",
                 "19 francos suicos", "pesos argentinos 19 hoje", "libras 19 hoje", "19 NZD hoje", "19 HKD hoje",
                 "19 INR hoje", "19 KRW hoje", "NZD 19 hoje", "HKD 19 hoje", "INR 19 hoje", "KRW 19 hoje",
                 "XYZ 19 hoje"]
        for sufixo in casos:
            r = nome_curto("Kit Potes Herméticos " + sufixo)
            self.assertTrue(r.startswith("Kit Potes Herméticos"), (sufixo, r))
            self.assertIsNone(re.search(r"\d|%|\$", r), (sufixo, r))
        for legit in ("Mop PRO 360 Refis", "Kit 3 Peças LED Luminária", "Papel A4 Kit 2 Pacotes",
                      "Kit Chaves 3/4 Inox", "Chave 1/2 polegada Kit", "Mesa 50x70cm Dobrável",
                      "Liquidificador Turbo 1200W"):
            self.assert_legit(legit)

    def test_codex23_lista_de_permitidos_fecha_por_construcao(self):  # [auditoria] 23a rodada
        casos = ["contovinteeum", "pilavinteeum", "GBPvinteeum", "contodezenovehoje", "piladezenovehoje",
                 "pilavintehoje", "GBPdezenovehoje", "diariadezenovehoje", "pratadezenove", "pratasdezenove",
                 "pctvinteeum", "pcvinteeum", "pctdezenovehoje", "pcdezenovehoje", "pctsetentahoje",
                 "p.c.setentahoje", "19 peso argentino", "peso argentino 19 hoje", "19 libra esterlina",
                 "libra esterlina 19 hoje", "19 coroas", "19 coroas suecas", "coroas suecas 19 hoje", "19 escudos",
                 "19 escudos cabo-verdianos", "19 soles", "19 soles peruanos", "19 kwanzas", "19 kwanzas angolanos",
                 "19 paus", "19 mangos", "19 GEL hoje", "GEL 19 hoje", "19 TOP hoje", "TOP 19 hoje", "19 gel hoje",
                 "19 mad hoje", "mad 19 hoje", "19 Mad hoje", "Mad 19 hoje", "MADdezenove", "dezenoveMAD",
                 "19 MADhoje", "½ dias", "¾ semanas", "½ durante o mes"]
        for barra in ("⁄", "∕"):
            for fim in ("dias", "longos dias", "durante o mes", "segs", "mins", "ds"):
                casos.append(f"19{barra}32 {fim}")
        oraculo_extenso = re.compile(r"\b(" + "|".join(sorted({"dezenove", "vinte", "setenta", "um"}, key=len,
                                                                  reverse=True)) + r")\b", re.IGNORECASE)
        for sufixo in casos:
            r = nome_curto("Kit Potes Herméticos " + sufixo)
            self.assertTrue(r.startswith("Kit Potes Herméticos"), (sufixo, r))
            self.assertIsNone(re.search(r"\d|%|\$|[½¾]", r), (sufixo, r))
            self.assertIsNone(oraculo_extenso.search(r), (sufixo, r))  # nem valor por extenso

    def test_codex24_colado_curto_moeda_antes_atalhos_config(self):  # [auditoria] 24a rodada
        casos = ["contodezhoje", "piladezhoje", "GBPdezhoje", "pratadezhoje", "pctdezhoje", "pcdezhoje",
                 "p.c.dezhoje", "pctcemhoje", "pctdozehoje", "peso argentino 19 un", "libra esterlina 19 un",
                 "coroas suecas 19 un", "escudos 19 un", "soles 19 un", "kwanzas 19 un", "paus 19 un",
                 "mangos 19 un", "GEL 19 un", "TOP 19 un", "gel 19 un", "top 19 un", "mad 19 un", "Mad 19 un",
                 "paus 19un", "GEL 19un", "custa 19un", "19 em 1 vez", "dinares 19 peças", "paus 19 peças"]
        for sufixo in casos:
            r = nome_curto("Kit Potes Herméticos " + sufixo)
            self.assertTrue(r.startswith("Kit Potes Herméticos"), (sufixo, r))
            self.assertIsNone(re.search(r"\d|%|\$|\bdez\b|\bcem\b|\bdoze\b", r), (sufixo, r))
        # o config nao reabre a lista: palavra de dinheiro/sigla curta nao entra, e nao acumula
        from robo.texto import _PERMITIDOS_APOS_NUMERO, registrar_vocabulario
        registrar_vocabulario(["coroa", "gel", "conto", "travesseiro"], recomecar=True)
        self.assertNotIn("coroa", _PERMITIDOS_APOS_NUMERO)
        self.assertNotIn("gel", _PERMITIDOS_APOS_NUMERO)
        self.assertIn("travesseiro", _PERMITIDOS_APOS_NUMERO)
        registrar_vocabulario(["almofadinha"], recomecar=True)
        self.assertNotIn("travesseiros", _PERMITIDOS_APOS_NUMERO - {"travesseiros"} | set())  # base intacta
        ler_nicho()  # devolve a lista do config real
        for legit in ("Gel Capilar 200ml Kit", "Kit 10 pcs Potes Herméticos", "Kit 3 em 1 Organizador",
                      "Fogão Cooktop 4 Queimadores Inox", "Sofá Dois Lugares Retrátil", "Couro Real 2 Peças Bolsa"):
            self.assert_legit(legit)

    def test_codex25_nenhum_numero_do_vendedor_na_legenda(self):  # [auditoria] 25a rodada
        casos = ["p.c.umhoje", "pct umhoje", "pc umhoje", "conto umhoje", "pila umhoje", "GBP umhoje", "gbp umhoje",
                 "gbp dezhoje", "dezgbphoje", "cemgelhoje", "pausdezhoje", "mangosdezhoje", "mangosdez",
                 "pausdoishoje", "mangosdozehoje", "dezpaus", "dezpaushoje", "paus dezhoje", "paus umhoje",
                 "mangos umhoje", "mangos 19 litros", "gbp hoje aqui 19 potes", "paus hoje aqui 19 pecas",
                 "19 em 1 pote", "mad 19 a 20 potes", "gbp 19 ate 20 potes", "paus 3 em 1", "mangos 19 x 2 potes",
                 "mad 19 em 2 potes", "mop 19 pecas", "mop 19 unidades", "mop 19 kg", "all 19 pecas", "19 mop",
                 "19 merreca", "19 grana", "19 bufunfa", "19 dindin", "19 trocados"]
        for moeda in ("paus", "mangos", "gel", "mad", "gbp"):
            for valor in ("19", "19,90"):
                for sep in ("", " "):
                    for un in ("kg", "mes"):
                        casos.append(f"{moeda} {valor}{sep}{un}")
        extenso = re.compile(r"\b(um|uma|dois|duas|tres|três|dez|doze|cem|vinte|dezenove|setenta)\b", re.IGNORECASE)
        for sufixo in casos:
            r = nome_curto("Kit Potes Herméticos " + sufixo)
            self.assertIsNone(re.search(r"\d|%|\$", r), (sufixo, r))
            self.assertIsNone(extenso.search(r), (sufixo, r))
            for tok in r.split():  # nem numero por extenso colado ("umhoje", "dezpaus")
                self.assertFalse(re.search(r"(?:^|[a-z])(?:um|dez|doze|cem|dois|vinte)(?:hoje|paus|gbp|gel|$)",
                                           tok.lower()) and tok.lower() not in ("vintage",), (sufixo, r, tok))

    def test_codex26_numerais_unicode_zero_meio_letras_gratuidade(self):  # [auditoria] 26a rodada
        casos = ["zero reais", "zero real", "zero euros", "zero pct", "zeroreais", "duzentas reais", "duzentas pratas",
                 "quinhentas reais", "duzentasreais", "quinhentasreais", "meio real", "meia libra", "meia pataca",
                 "meio pct", "meioreal", "meiopct", "por meioreal", "meiorealhoje", "zerohoje",
                 "Ⅻ reais", "XII reais", "XIX reais", "十 reais", "〇 reais", "௰ reais", "৴ reais",
                 "cemmop", "ummop", "dezmop", "cemall", "umall", "dezall", "cemmophoje", "ummophoje", "dezallhoje",
                 "d e z paus", "v i n t e mangos", "gratuito", "gratuita", "gratuitamente", "gratuidade",
                 "sem pagar", "sem pagar nada", "nada a pagar", "na faixa", "por conta da casa", "cortesia",
                 "menor valor", "menor valor do mercado", "valor mínimo", "imbatível", "melhor valor"]
        for sufixo in casos:
            self.assertEqual(nome_curto("Kit Potes Herméticos " + sufixo), "Kit Potes Herméticos", sufixo)
        self.assertEqual(nome_curto("Kit Meias Femininas Algodão"), "Kit Meias Femininas Algodão")
        self.assertEqual(nome_curto("Meia-Calça Feminina Fio"), "Meia-Calça Feminina Fio")
        self.assertEqual(nome_curto("Camiseta Feminina XL Algodão"), "Camiseta Feminina Algodão")  # XL=40: fora
        self.assertEqual(nome_curto("Fone Bluetooth Hands Free"), "Fone Bluetooth")

    def test_codex27_vocabulario_permitido(self):  # [auditoria] 27a rodada
        from robo import vocabulario as V
        from robo.texto import _NUMSET, _no_vocabulario, tem_alegacao
        casos = ["Ⅰ reais hoje", "ⅰ reais", "Ⅴ reais", "Ⅹ reais", "Ⅿ reais", "I reais", "V reais", "X reais",
                 "xix reais", "XL reais", "trilhão reais", "quatrilhão reais", "duzia reais", "terço de real",
                 "quarto de real", "sétimo de real", "libra e meia", "meia de libra", "meio-do-real", "d. e. z. paus",
                 "v. i. n. t. e. mangos", "de z paus", "vin te paus", "não custa nada", "não paga nada",
                 "sem cobrança", "sem cobrar", "sem desembolsar", "sem qualquer custo", "sem nenhum custo",
                 "isento de pagamento", "a custo nulo", "custo nenhum", "custo inexistente", "supergratuito",
                 "sem-pagar", "na-faixa", "valor mais baixo do mercado", "menores valores do mercado",
                 "valor inferior ao da concorrência", "menorvalor", "valor reduzido", "valor irrisório",
                 "valor simbólico", "imbativel", "melhor valor"]
        for sufixo in casos:
            r = nome_curto("Kit Potes Herméticos " + sufixo)
            self.assertEqual(r, "Kit Potes Herméticos", (sufixo, r))
        # o proprio vocabulario e limpo: so letras latinas, nenhum numero/extenso/alegacao
        for w in V.PALAVRAS | V.CONECTORES:
            self.assertRegex(w, r"^[a-z]+$", w)
            self.assertNotIn(w, _NUMSET, w)
            self.assertFalse(tem_alegacao(w), w)
        for w in ("i", "v", "x", "l", "c", "d", "m", "xl", "xix", "real", "reais", "gratis", "custo", "valor",
                  "preco", "menor", "melhor", "metade", "dobro", "meio", "zero", "nada", "cortesia", "free"):
            self.assertFalse(w in V.PALAVRAS and _no_vocabulario(w), w)

    def test_propriedade_toda_palavra_publicada_e_do_vocabulario(self):
        import random
        from robo.texto import _no_vocabulario
        from robo import vocabulario as V
        rnd = random.Random(27)
        pecas = ["Kit", "Potes", "Herméticos", "Ⅻ", "ⅰ", "XIX", "XL", "19", "reais", "não", "custa", "nada", "grátis",
                 "menor", "valor", "d", "e", "z", "paus", "sem", "cobrança", "de", "com", "Organizador", "Inox", "%",
                 "R$", "meia", "libra", "terço", "trilhão", "vin", "te", "cortesia", "isento", "pagamento", "Mop"]
        for _ in range(3000):
            titulo = " ".join(rnd.choice(pecas) for _ in range(rnd.randint(1, 10)))
            r = nome_curto(titulo)
            if r == "Produto":
                continue
            for tok in r.split():
                self.assertTrue(V.normalizar_palavra(tok) in V.CONECTORES or _no_vocabulario(tok), (titulo, r, tok))

    def test_propriedade_titulos_hostis_aleatorios(self):
        """Milhares de titulos montados ao acaso com pecas hostis: o nome da legenda nunca
        tem algarismo, %, $, nem numero por extenso (solto ou colado)."""
        import random
        rnd = random.Random(20261017)
        pecas = ["Kit", "Potes", "Herméticos", "19", "19,90", "7O%", "70%", "１９", "٪", "R$", "$", "BRL", "gbp", "paus",
                 "mangos", "dez", "vinte", "e", "um", "dezenove", "hoje", "por", "a partir de", "x", "2x", "em", "1",
                 "kg", "ml", "un", "pecas", "r3al", "re-al", "p c t", "pct", "½", "19⁄32", "/", "mes", "cada", "no",
                 "pix", "Mop", "Gel", "Inox", "Organizador", "umhoje", "dezpaus", "contovinte", "MADdezenove", "-", ":",
                 "zero", "meio", "meia", "Ⅻ", "XIX", "十", "〇", "d e z", "v i n t e", "duzentas", "zeroreais", "meioreal",
                 "cemmop", "gratuito", "reais", "libra", "pesos"]
        extenso = re.compile(r"\b(um|uma|dois|duas|tres|três|dez|doze|cem|vinte|dezenove|setenta)\b", re.IGNORECASE)
        for _ in range(3000):
            titulo = " ".join(rnd.choice(pecas) for _ in range(rnd.randint(1, 9)))
            r = nome_curto(titulo)
            self.assertFalse(any(unicodedata.numeric(c, None) is not None for c in r), (titulo, r))
            self.assertIsNone(re.search(r"\d|%|\$|\bXI*X?\b|\bXII\b|\bXIX\b", r), (titulo, r))
            self.assertIsNone(extenso.search(r), (titulo, r))
            self.assertIsNone(re.search(r"\b(zero|duzentas|meio\s+real|meia\s+libra|d e z|v i n t e)\b", r, re.I), (titulo, r))
            for tok in r.lower().split():
                self.assertNotIn(tok, ("umhoje", "dezpaus", "contovinte", "maddezenove", "zeroreais", "meioreal",
                                       "cemmop"), (titulo, r))

    def test_23_perdas_aceitas_da_lista_de_permitidos(self):
        """Corte excessivo e RISCO aceito pelo desenho: numero seguido de palavra fora da lista sai."""
        self.assertEqual(nome_curto("Brinco Prata 925 Kit 2 Pares"), "Brinco Prata")
        self.assertEqual(nome_curto("Mop PRO 360 com 2 Refis"), "Mop PRO")
        self.assertEqual(nome_curto("Mixer 500 Offset Pro"), "Produto")

    def test_oraculo_independente_sem_numero_monetario_ou_percentual(self):
        """Oraculo que NAO usa o detector: nenhum nome final de todos os casos das auditorias
        pode ter %, $, ou digito/numero por extenso seguido de unidade de dinheiro/percentual."""
        casos = ["70% OFF", "Kit Potes ７０％", "Kit 70٪", "Kit 19 reais", "Kit VinteReais", "Kit 70 p c t",
                 "Kit 19 r e a i s", "Kit por 19 no Pix", "Kit 70 percent", "Kit BRL 19", "Kit 19,9 no Pix",
                 "Kit 19 r3al", "Kit UmReal", "Kit 19 d o l a r", "Kit 70 pontos percentuais", "Kit por 19 hoje"]
        # oraculo: texto sem espacos/pontuacao/acentos, leet desfeito; nada de numero (algarismo ou
        # extenso) seguido de unidade de dinheiro/percentual, nem % ou $
        unidades = r"(reai|real|pct|percent|porcent|off|brl|usd|eur|centav|prata|conto|dolar|pix)"
        numeros = r"(\d|um|vinte|setenta|dezenove)"
        proibido = re.compile(r"[%$]|" + numeros + unidades + r"|por" + numeros)
        for titulo in casos:
            plano = unicodedata.normalize("NFKD", nome_curto(titulo).lower())
            plano = re.sub(r"[^a-z0-9%$]", "", "".join(c for c in plano if not unicodedata.combining(c)))
            plano = re.sub(r"(?<=[a-z])[0134](?=[a-z])", lambda m: "oiea"["0134".index(m.group())], plano)
            self.assertIsNone(proibido.search(plano), (titulo, plano))

    def test_nome_da_legenda_nunca_tem_alegacao(self):  # garantia final, qualquer titulo
        from robo.texto import tem_alegacao
        for titulo in ("70% OFF", "Super Promoção Desconto Imperdível", "Preço", "Kit Mop 50% Off Barato",
                       "Leve 3 Pague 2 Kit Potes", "R$ 9,90 Kit Potes Herméticos"):
            self.assertFalse(tem_alegacao(nome_curto(titulo)), titulo)

    def test_vitrine_avisa_titulo_cortado(self):
        c = avaliar_candidato(oferta(nome="Kit Potes Herméticos Cozinha 70% OFF"), V_OK, CFG)
        c.link = "https://s.shopee.com.br/a"
        html_ = gerar_html({"cozinha": [c]}, Counter(), CFG, datetime(2026, 10, 17), {"lidas": 1}, [])
        self.assertIn("título do vendedor tinha alegação", html_)

    def test_mensagem_curta_de_por(self):
        from robo.texto import mensagem
        c = avaliar_candidato(oferta(), V_OK, CFG)
        c.link = "https://s.shopee.com.br/abc"
        t = mensagem(c, "🍳")
        self.assertEqual(t.splitlines()[0], "#publi · link de afiliado")
        self.assertIn("De R$ 80,00 por R$ 50,00 (-38%)", t)  # 'de' = referencia do NOSSO historico
        self.assertIn("👉 https://s.shopee.com.br/abc", t)
        c2 = avaliar_candidato(oferta(desconto=60), V_SEM, CFG)  # sem historico: sem 'de'
        c2.link = "https://s.shopee.com.br/abc"
        t2 = mensagem(c2)
        self.assertNotIn("De R$", t2)
        self.assertIn("Por R$ 50,00", t2)
        self.assertNotIn("60", t2)

    def test_codex30_variacao_de_preco_e_aviso_na_tela(self):  # [auditoria] 30a rodada
        from robo.texto import mensagem
        from robo.vitrine import achados
        import robo.painel as P
        # contraexemplo do Codex: historico 80/160 em 3 dias espacados, oferta 50/100
        hist = h((20, 80, 160), (13, 80, 160), (6, 80, 160))
        v = avaliar(50, hist, AGORA, atual_max=100)
        self.assertTrue(v.confirmado, v.rotulo)
        c = avaliar_candidato(oferta(preco_min=50.0, preco_max=100.0), v, CFG)
        c.link = "https://s.shopee.com.br/abc"
        t = mensagem(c)
        self.assertIn("Opção mais barata: de R$ 80,00 por R$ 50,00 (-38%)", t)
        self.assertFalse(any(linha.startswith("De R$") for linha in t.splitlines()), t)
        # sem historico e com variacoes: "a partir de"
        c2 = avaliar_candidato(oferta(preco_min=50.0, preco_max=100.0), V_SEM, CFG)
        c2.link = "https://s.shopee.com.br/abc"
        self.assertIn("Por a partir de R$ 50,00", mensagem(c2))
        # aviso de conferencia chega a tela nova
        c3 = avaliar_candidato(oferta(nome="Kit Higiene Bebê 5 peças"), V_OK, CFG)
        c3.link = "https://s.shopee.com.br/abc"
        lista = achados({"bebe": [c3], "cozinha": [c]}, CFG)
        por_nome = {a["tag"]: a for a in lista}
        self.assertIn("NBCAL", por_nome["bebe"]["aviso"])
        self.assertTrue(por_nome["cozinha"]["variacoes"])
        html_bebe = P._card(por_nome["bebe"])
        self.assertIn("aviso-card", html_bebe)
        self.assertIn("NBCAL", html_bebe)
        html_var = P._card(por_nome["cozinha"])
        self.assertIn("a partir de", html_var)
        self.assertIn("Opção mais barata: de", html_var)

    def test_codex31_qualquer_diferenca_de_opcao_e_variacao(self):  # [auditoria] 31a rodada
        from robo.texto import mensagem, tem_variacoes
        from robo.vitrine import achados
        import robo.painel as P
        hist = h((20, 80, 80.80), (13, 80, 80.80), (6, 80, 80.80))
        v = avaliar(50, hist, AGORA, atual_max=50.50)
        c = avaliar_candidato(oferta(preco_min=50.0, preco_max=50.50), v, CFG)
        c.link = "https://s.shopee.com.br/abc"
        self.assertTrue(tem_variacoes(c.oferta))
        self.assertIn("Opção mais barata: de R$ 80,00 por R$ 50,00", mensagem(c))
        card = P._card(achados({"cozinha": [c]}, CFG)[0])
        self.assertIn("a partir de", card)
        # preco realmente unico: sem qualificacao
        unico = avaliar_candidato(oferta(preco_min=50.0, preco_max=50.0), V_OK, CFG)
        unico.link = "https://s.shopee.com.br/abc"
        self.assertFalse(tem_variacoes(unico.oferta))
        self.assertIn("De R$ 80,00 por R$ 50,00 (-38%)", mensagem(unico))
        self.assertNotIn("a partir de", P._card(achados({"cozinha": [unico]}, CFG)[0]))

    def test_legenda_publi_na_primeira_linha(self):  # [auditoria] CONAR
        c = avaliar_candidato(oferta(), V_OK, CFG)
        c.link = "https://s.shopee.com.br/abc"
        t = legenda(c, "🍳")
        self.assertEqual(t.splitlines()[0], AVISO_TOPO)
        self.assertTrue(t.splitlines()[0].startswith("#publi"))
        self.assertIn("https://s.shopee.com.br/abc", t)
        self.assertIn("R$ 50,00", t)
        self.assertIn("38% abaixo do preço normal", t)
        self.assertNotIn("-40%", t)  # o % anunciado pela Shopee nunca vai para a legenda

    def test_legenda_sem_historico_nao_promete_desconto(self):  # [auditoria] CDC
        c = avaliar_candidato(oferta(desconto=60), V_SEM, CFG)
        c.link = "https://s.shopee.com.br/abc"
        t = legenda(c)
        self.assertNotIn("✅", t)
        self.assertNotIn("%", t.split("\n", 1)[1].replace("#", ""))

    def test_legenda_feed_sem_link_e_com_cupom(self):
        c = avaliar_candidato(oferta(), V_OK, CFG)
        c.link = "https://s.shopee.com.br/abc"
        t = legenda(c, canal="feed", cupom="ACHADO10")
        self.assertNotIn("https://", t)
        self.assertIn("ACHADO10", t)


class TestVitrine(unittest.TestCase):
    def test_url_segura(self):
        self.assertEqual(url_segura("javascript:alert(1)"), "")
        self.assertEqual(url_segura("data:text/html,x"), "")
        self.assertEqual(url_segura("https://s.shopee.com.br/a"), "https://s.shopee.com.br/a")

    def test_html_escapa_dado_da_api(self):
        c = avaliar_candidato(oferta(nome='Pote <script>alert(1)</script> cozinha', imagem="javascript:x"),
                              V_OK, CFG)
        c.link = "https://s.shopee.com.br/a"
        html_ = gerar_html({"cozinha": [c]}, Counter(), CFG, datetime(2026, 10, 17), {"lidas": 1}, [c])
        self.assertNotIn("<script>alert", html_)
        self.assertNotIn('src="javascript', html_)
        self.assertIn('data-tag="top"', html_)

    def test_csv_neutraliza_formula(self):  # [auditoria]
        self.assertEqual(celula_segura("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(celula_segura("@SUM"), "'@SUM")
        self.assertEqual(celula_segura("Loja Boa"), "Loja Boa")
        c = avaliar_candidato(oferta(loja="=1+1"), V_OK, CFG)
        c.link = "https://s.shopee.com.br/a"
        with tempfile.TemporaryDirectory() as tmp:
            arq = salvar_saidas(Path(tmp), {"cozinha": [c]}, Counter(), CFG, datetime(2026, 10, 17), {})
            self.assertIn(";'=1+1;", arq["csv"].read_text(encoding="utf-8-sig"))


# ----------------------------------------------------------------- rodada
class FakeClienteRodada:
    def __init__(self, ofertas, falha_link=False, reconf=None, termo="potes hermeticos"):
        self.ofertas = ofertas
        self.falha_link = falha_link
        self.reconf = reconf or {}  # item_id -> Oferta | None (sumiu)
        self.termo = termo
        self.chamadas = 0

    def buscar_ofertas(self, keyword=None, page=1, item_id=None, **_):
        self.chamadas += 1
        if item_id is not None:
            if item_id in self.reconf:
                return ([self.reconf[item_id]] if self.reconf[item_id] else []), False
            return [o for o in self.ofertas if o.item_id == item_id], False
        return (list(self.ofertas) if keyword == self.termo and page == 1 else []), False

    def link_curto(self, url, sub_ids=None):
        self.chamadas += 1
        if self.falha_link:
            raise ErroShopee(11000, "falhou")
        return "https://s.shopee.com.br/sub-" + "-".join(sub_ids or [])


def semear(banco, item_id, *pares):
    for d, p in pares:
        banco.registrar(oferta(item_id=item_id, preco_min=p, preco_max=p), ts=AGORA - d * DIA)


def quieto(_):
    pass


class TestRodada(unittest.TestCase):
    def test_ponta_a_ponta(self):
        ofs = [oferta(item_id=1), oferta(item_id=2, nome="Mamadeira Anticólica", shop_id=3),
               oferta(item_id=3, nome="Garrafa Térmica Inox", shop_id=4, desconto=10)]
        banco = Banco(":memory:")
        semear(banco, 1, (20, 80), (10, 80), (3, 82))
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada(ofs), banco, CFG, Path(tmp), agora=AGORA, log=quieto)
            self.assertEqual(res.total_escolhidos, 1)
            c = res.escolhidos["cozinha"][0]
            self.assertEqual(c.veredito.status, "menor_preco")
            self.assertEqual(c.link, "https://s.shopee.com.br/sub-ig-cozinha")
            self.assertTrue(c.link_rastreado and c.reconferido)
            self.assertEqual(c.selo, "NOVO")
            self.assertEqual(res.top, [c])
            self.assertTrue(any("NBCAL" in m for m in res.recusados))
            for nome in ("vitrine.html", "ofertas.csv", "legendas.txt", "legendas_feed.txt", "ofertas.json"):
                self.assertTrue((Path(tmp) / "ultima" / nome).exists(), nome)
        self.assertEqual(len(banco.historico(1, AGORA - 30 * DIA)), 4)  # leitura de hoje gravada

    def test_link_falha_usa_offerlink_e_avisa(self):  # [auditoria]
        banco = Banco(":memory:")
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada([oferta()], falha_link=True), banco, CFG, Path(tmp),
                        agora=AGORA, log=quieto)
        c = res.escolhidos["cozinha"][0]
        self.assertEqual(c.link, "https://s.shopee.com.br/abc")
        self.assertFalse(c.link_rastreado)
        self.assertTrue(res.erros)

    def test_credencial_ruim_aborta(self):
        class Ruim(FakeClienteRodada):
            def buscar_ofertas(self, **_):
                raise ErroShopee(10020, "Invalid Signature")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ErroShopee):
            rodar(Ruim([]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)

    def test_rede_fora_aborta_e_preserva_ultima_vitrine(self):  # [auditoria]
        class SemRede(FakeClienteRodada):
            def buscar_ofertas(self, **_):
                self.chamadas += 1
                raise ErroShopee(None, "falha de rede")
        with tempfile.TemporaryDirectory() as tmp:
            ultima = Path(tmp) / "ultima"
            ultima.mkdir()
            (ultima / "vitrine.html").write_text("BOA", encoding="utf-8")
            cli = SemRede([])
            with self.assertRaises(ErroColeta):
                rodar(cli, Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
            self.assertEqual((ultima / "vitrine.html").read_text(encoding="utf-8"), "BOA")
            self.assertEqual(cli.chamadas, CFG["coleta"]["max_falhas_seguidas"])

    def test_historico_salvo_antes_de_erro_fatal(self):  # [auditoria]
        class CaiNoMeio(FakeClienteRodada):
            def buscar_ofertas(self, keyword=None, **kw):
                if self.chamadas >= 1:
                    raise ErroShopee(10033, "conta congelada")
                self.chamadas += 1
                return [oferta(item_id=7)], False
        banco = Banco(":memory:")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ErroShopee):
            rodar(CaiNoMeio([]), banco, CFG, Path(tmp), agora=AGORA, log=quieto)
        self.assertEqual(len(banco.historico(7, 0)), 1)

    def test_reconferencia_derruba_e_reserva_ocupa(self):  # [auditoria]
        ofs = [oferta(item_id=1, shop_id=1, nome="Garrafa Térmica Inox 1L", vendas=9000),
               oferta(item_id=2, shop_id=2, nome="Tábua de Corte Bambu", vendas=500)]
        subiu = oferta(item_id=1, shop_id=1, nome="Garrafa Térmica Inox 1L", preco_min=70.0, preco_max=70.0)
        f = dict(CFG["filtros"], max_por_tag=1, reserva_por_tag=3)
        cfg = dict(CFG, filtros=f)
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada(ofs, reconf={1: subiu}), Banco(":memory:"), cfg, Path(tmp),
                        agora=AGORA, log=quieto)
        self.assertEqual([c.oferta.item_id for c in res.escolhidos["cozinha"]], [2])
        self.assertEqual(res.recusados["preço subiu na reconferência"], 1)

    def test_nao_repete_e_marca_baixou_de_novo(self):  # [auditoria] memoria do que ja foi sugerido
        banco = Banco(":memory:")
        with tempfile.TemporaryDirectory() as tmp:
            r1 = rodar(FakeClienteRodada([oferta()]), banco, CFG, Path(tmp), agora=AGORA, log=quieto)
            self.assertEqual(r1.total_escolhidos, 1)
            r2 = rodar(FakeClienteRodada([oferta()]), banco, CFG, Path(tmp), agora=AGORA + DIA, log=quieto)
            self.assertEqual(r2.total_escolhidos, 0)
            self.assertTrue(any("já sugerido" in m for m in r2.recusados))
            mais_barato = oferta(preco_min=44.0, preco_max=44.0)
            r3 = rodar(FakeClienteRodada([mais_barato]), banco, CFG, Path(tmp), agora=AGORA + 2 * DIA, log=quieto)
            self.assertEqual(r3.escolhidos["cozinha"][0].selo, "BAIXOU DE NOVO")

    def test_reconferencia_refaz_o_julgamento(self):  # [auditoria] 75 -> 77 vira queda de 23%
        banco = Banco(":memory:")
        semear(banco, 1, (20, 100), (13, 100), (6, 100))
        ofs = [oferta(item_id=1, preco_min=70.0, preco_max=70.0)]  # 30% (passa no corte exigente)
        reconf = {1: oferta(item_id=1, preco_min=72.0, preco_max=72.0)}  # vira 28%: cai na reconferencia
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada(ofs, reconf=reconf), banco, CFG, Path(tmp), agora=AGORA, log=quieto)
        self.assertEqual(res.total_escolhidos, 0)
        self.assertTrue(any(m.startswith("na reconferência: queda real") for m in res.recusados), res.recusados)

    def test_reserva_nao_some_por_limite_de_loja(self):  # [auditoria] os 2 primeiros da loja ja sugeridos
        banco = Banco(":memory:")
        nomes = ["Garrafa Térmica Inox 1L", "Tábua de Corte Bambu", "Jogo de Facas Chef"]
        ofs = [oferta(item_id=i + 1, nome=n, vendas=9000 - i * 1000) for i, n in enumerate(nomes)]
        for o in ofs[:2]:
            banco.registrar_sugestao(o.item_id, AGORA - DIA, o.preco_min, "cozinha")
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada(ofs), banco, CFG, Path(tmp), agora=AGORA, log=quieto)
        self.assertEqual([c.oferta.item_id for c in res.escolhidos["cozinha"]], [3])

    def test_sugestao_so_conta_se_a_vitrine_saiu(self):  # [auditoria]
        banco = Banco(":memory:")
        original = pipeline_mod.salvar_saidas
        pipeline_mod.salvar_saidas = lambda *a, **k: (_ for _ in ()).throw(OSError("disco cheio"))
        try:
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(OSError):
                rodar(FakeClienteRodada([oferta()]), banco, CFG, Path(tmp), agora=AGORA, log=quieto)
        finally:
            pipeline_mod.salvar_saidas = original
        self.assertIsNone(banco.ultima_sugestao(1, AGORA + DIA))

    def test_saida_parcial_e_avisada(self):  # [auditoria] csv aberto no Excel
        original = pipeline_mod.shutil.copy2

        def copia(src, dst):
            if str(dst).endswith("ofertas.csv"):
                raise PermissionError(13, "em uso")
            return original(src, dst)
        pipeline_mod.shutil.copy2 = copia
        try:
            with tempfile.TemporaryDirectory() as tmp:
                res = rodar(FakeClienteRodada([oferta()]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
        finally:
            pipeline_mod.shutil.copy2 = original
        self.assertTrue(res.saida_parcial)
        self.assertTrue(any("ofertas.csv" in a for a in res.avisos))

    def test_historico_guarda_a_menor_leitura_da_janela(self):  # [auditoria] 2a e 4a rodadas
        banco = Banco(":memory:")
        banco.registrar(oferta(preco_min=150.0, preco_max=150.0), ts=AGORA)
        banco.registrar(oferta(preco_min=100.0, preco_max=100.0), ts=AGORA + 60)
        banco.registrar(oferta(preco_min=120.0, preco_max=120.0), ts=AGORA + 120)
        self.assertEqual([p for _, p, _ in banco.historico(1, 0)], [100.0])

    def test_codex4_reconferencia_um_pouco_mais_cara_nao_vira_menor_preco(self):  # [auditoria]
        banco = Banco(":memory:")
        semear(banco, 1, (20, 100), (13, 100), (6, 100))
        reconf = {1: oferta(preco_min=61.0, preco_max=61.0)}
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada([oferta(preco_min=60.0, preco_max=60.0)], reconf=reconf),
                        banco, CFG, Path(tmp), agora=AGORA, log=quieto)
        c = res.escolhidos["cozinha"][0]
        self.assertEqual(c.oferta.preco_min, 61.0)
        self.assertNotEqual(c.veredito.status, "menor_preco")
        self.assertNotIn("Menor preço", legenda(c))

    def test_codex5_duas_buscas_60_e_61_nao_viram_menor_preco(self):  # [auditoria] 5a rodada
        class DuasBuscas(FakeClienteRodada):
            def buscar_ofertas(self, keyword=None, page=1, item_id=None, **kw):
                self.chamadas += 1
                if item_id is not None:
                    return [oferta(preco_min=61.0, preco_max=61.0)], False
                if keyword == "potes hermeticos":
                    return [oferta(preco_min=60.0, preco_max=60.0)], False
                if keyword == "organizador cozinha":
                    return [oferta(preco_min=61.0, preco_max=61.0)], False
                return [], False
        for reconferir in (True, False):
            banco = Banco(":memory:")
            semear(banco, 1, (20, 100), (13, 100), (6, 100))
            cfg = dict(CFG, coleta=dict(CFG["coleta"], reconferir_escolhidos=reconferir))
            with tempfile.TemporaryDirectory() as tmp:
                res = rodar(DuasBuscas([]), banco, cfg, Path(tmp), agora=AGORA, log=quieto)
            c = res.escolhidos["cozinha"][0]
            self.assertEqual(c.oferta.preco_min, 61.0)
            self.assertNotEqual(c.veredito.status, "menor_preco", reconferir)
            self.assertNotIn("Menor preço", legenda(c))

    def test_codex6_leitura_fundida_segundos_antes_conta(self):  # [auditoria] 6a rodada
        for reconferir in (True, False):
            banco = Banco(":memory:")
            semear(banco, 1, (20, 100), (13, 100), (6, 100))
            banco.registrar(oferta(preco_min=100.0, preco_max=100.0), ts=AGORA - 30)  # rodada interrompida
            cfg = dict(CFG, coleta=dict(CFG["coleta"], reconferir_escolhidos=reconferir))

            class Cli(FakeClienteRodada):
                def buscar_ofertas(self, keyword=None, page=1, item_id=None, **kw):
                    self.chamadas += 1
                    if item_id is not None:
                        return [oferta(preco_min=61.0, preco_max=61.0)], False
                    if keyword == "potes hermeticos":
                        return [oferta(preco_min=60.0, preco_max=60.0)], False
                    if keyword == "organizador cozinha":
                        return [oferta(preco_min=61.0, preco_max=61.0)], False
                    return [], False
            with tempfile.TemporaryDirectory() as tmp:
                res = rodar(Cli([]), banco, cfg, Path(tmp), agora=AGORA, log=quieto)
            c = res.escolhidos["cozinha"][0]
            self.assertNotEqual(c.veredito.status, "menor_preco", reconferir)

    def test_ultima_recuperada_mesmo_se_a_rodada_seguinte_falha(self):  # [auditoria] 6a rodada (risco)
        class SemRede(FakeClienteRodada):
            def buscar_ofertas(self, **_):
                raise ErroShopee(None, "falha de rede")
        with tempfile.TemporaryDirectory() as tmp:
            velha = Path(tmp) / "ultima.velha"
            velha.mkdir()
            (velha / "vitrine.html").write_text("ANTIGA", encoding="utf-8")
            with self.assertRaises(ErroColeta):
                rodar(SemRede([]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
            self.assertEqual((Path(tmp) / "ultima" / "vitrine.html").read_text(encoding="utf-8"), "ANTIGA")

    def test_ultima_recuperada_apos_interrupcao(self):  # [auditoria] 5a rodada (risco)
        with tempfile.TemporaryDirectory() as tmp:
            velha = Path(tmp) / "ultima.velha"
            velha.mkdir()
            (velha / "vitrine.html").write_text("ANTIGA", encoding="utf-8")
            original = pipeline_mod.salvar_saidas
            pipeline_mod.salvar_saidas = lambda *a, **k: (_ for _ in ()).throw(OSError("x"))
            try:
                with self.assertRaises(OSError):
                    rodar(FakeClienteRodada([oferta()]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
            finally:
                pipeline_mod.salvar_saidas = original
            rodar(FakeClienteRodada([oferta(item_id=5)]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
            self.assertTrue((Path(tmp) / "ultima" / "vitrine.html").exists())
            self.assertFalse(velha.exists())

    def test_erro_temporario_na_reconferencia_tambem_recusa(self):  # [auditoria] 4a rodada (risco)
        class Instavel(FakeClienteRodada):
            def buscar_ofertas(self, item_id=None, **kw):
                if item_id is not None:
                    raise ErroShopee(None, "falha de rede")
                return super().buscar_ofertas(**kw)
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(Instavel([oferta()]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
        self.assertEqual(res.total_escolhidos, 0)

    def test_reconferencia_grava_preco_no_historico(self):  # [auditoria] 3a rodada
        banco = Banco(":memory:")
        reconf = {1: oferta(preco_min=48.0, preco_max=48.0)}
        with tempfile.TemporaryDirectory() as tmp:
            rodar(FakeClienteRodada([oferta()], reconf=reconf), banco, CFG, Path(tmp), agora=AGORA, log=quieto)
        self.assertEqual(banco.historico(1, 0)[-1][1], 48.0)

    def test_erro_permanente_na_reconferencia_recusa(self):  # [auditoria] 3a rodada
        class Quebra(FakeClienteRodada):
            def buscar_ofertas(self, item_id=None, **kw):
                if item_id is not None:
                    raise ErroShopee(11001, "parametro invalido")
                return super().buscar_ofertas(**kw)
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(Quebra([oferta()]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
        self.assertEqual(res.total_escolhidos, 0)
        self.assertEqual(res.recusados["erro na reconferência"], 1)

    def test_ultima_trocada_inteira(self):  # [auditoria] sem misturar versoes
        with tempfile.TemporaryDirectory() as tmp:
            ultima = Path(tmp) / "ultima"
            ultima.mkdir()
            (ultima / "sobra_velha.txt").write_text("x", encoding="utf-8")
            res = rodar(FakeClienteRodada([oferta()]), Banco(":memory:"), CFG, Path(tmp), agora=AGORA, log=quieto)
            self.assertFalse(res.saida_parcial)
            self.assertEqual(sorted(p.name for p in ultima.iterdir()), sorted(p.name for p in res.arquivos.values()))
            self.assertFalse((Path(tmp) / "ultima.nova").exists() or (Path(tmp) / "ultima.velha").exists())

    def test_link_em_cache(self):
        banco = Banco(":memory:")
        banco.salvar_link(1, ["ig", "cozinha"], "https://s.shopee.com.br/cache", ts=AGORA - DIA)
        self.assertEqual(banco.link_salvo(1, ["ig", "cozinha"], 7 * DIA, AGORA), "https://s.shopee.com.br/cache")
        self.assertIsNone(banco.link_salvo(1, ["ig", "cozinha"], 0.5 * DIA, AGORA))

    def test_subids_so_alfanumericos(self):
        self.assertEqual(montar_subids(["ig", "{tag}", "x y-z"], "bebê"), ["ig", "beb", "xyz"])

    def test_mesma_leitura_nao_duplica(self):
        banco = Banco(":memory:")
        self.assertTrue(banco.registrar(oferta(), ts=AGORA))
        self.assertFalse(banco.registrar(oferta(), ts=AGORA + 600))

    def test_trava_impede_rodada_dupla(self):
        with tempfile.TemporaryDirectory() as tmp:
            trava = Path(tmp) / "rodando.lock"
            with Trava(trava):
                with self.assertRaises(RodadaEmAndamento):
                    with Trava(trava):
                        pass
            self.assertFalse(trava.exists())


class TestConfig(unittest.TestCase):
    def test_nicho_com_bom(self):  # [auditoria] Bloco de Notas salva "UTF-8 com BOM"
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nicho.json"
            orig = (Path(__file__).resolve().parent.parent / "config" / "nicho.json").read_text(encoding="utf-8")
            p.write_text(orig, encoding="utf-8-sig")
            self.assertIn("tags", ler_nicho(p))


if __name__ == "__main__":
    unittest.main()
