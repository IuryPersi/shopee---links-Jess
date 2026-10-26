"""'Montar postagem': link gerado a mao + preco -> mensagem conferida. Respostas FALSAS, sem internet."""
from __future__ import annotations

import http.client
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from robo.config import ler_nicho  # noqa: E402
import robo.postagem as POSTAGEM  # noqa: E402
from robo.postagem import assinatura, ler_preco, mensagens, montar_postagem  # noqa: E402

_PASTA_CHAVE = tempfile.TemporaryDirectory()  # a chave dos testes nunca vai para dados/ de verdade
POSTAGEM.PASTA_CHAVE = _PASTA_CHAVE.name

CURTO = "https://s.shopee.com.br/AbC123"
MARCA = "?utm_medium=affiliates&utm_source=an_10000000001"
ALMOFADA = "https://shopee.com.br/Almofada-de-Amamenta%C3%A7%C3%A3o-Macia-i.55.987654"
MAMADEIRA = "https://shopee.com.br/Mamadeira-Anticolica-260ml-i.55.111"
SEM_NOME = "https://shopee.com.br/product/55/222"
CFG = ler_nicho()


def abridor(final: str):
    """O link curto vai (301) para `final` + marcacao, que responde 200."""
    def abrir(url, timeout):
        if url == CURTO:
            return 301, final + MARCA
        if url == final + MARCA:
            return 200, None
        raise OSError("sem rede")
    return abrir


class TestPreco(unittest.TestCase):
    def test_formatos(self):
        for texto, valor in (("29,90", 29.9), ("R$ 29,90", 29.9), ("R$29,9", 29.9), ("29.90", 29.9),
                             ("30", 30.0), ("1.299,90", 1299.9), ("1.299", 1299.0)):
            self.assertEqual(ler_preco(texto), valor, texto)
        for texto in ("", "abc", "0", "0,10", "29,999", "-5", "200000", "29,90 reais", "1e3", None):
            self.assertIsNone(ler_preco(texto), texto)


class TestMontar(unittest.TestCase):
    def test_link_certo_monta_a_mensagem_so_com_por(self):
        r = montar_postagem(CURTO, "39,90", CFG, abrir=abridor(ALMOFADA), confirmado=True)
        self.assertTrue(r["ok"], r["motivos"])
        linhas = r["mensagem"].splitlines()
        self.assertEqual(linhas[0], "#publi · link de afiliado")
        self.assertTrue(linhas[1].startswith("🤰 "), linhas[1])
        self.assertIn("Almofada", linhas[1])
        self.assertEqual(linhas[2], "Por R$ 39,90")
        self.assertEqual(linhas[3], f"👉 {CURTO}")
        self.assertEqual(linhas[-1], "Preço pode mudar a qualquer momento.")
        self.assertNotIn("De R$", r["mensagem"])  # sem historico, nunca o "De" (decisao do dono)
        self.assertIn("🔗 Link nos stories", r["mensagem_feed"])
        self.assertNotIn(CURTO, r["mensagem_feed"])

    def test_nbcal_barra_pelo_nome_do_endereco_e_pelo_digitado(self):
        r = montar_postagem(CURTO, "29,90", CFG, abrir=abridor(MAMADEIRA))
        self.assertFalse(r["ok"])
        self.assertNotIn("mensagem", r)
        self.assertTrue(any("NBCAL" in m for m in r["motivos"]), r["motivos"])
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Kit Mamadeira e Chupeta", abrir=abridor(ALMOFADA))
        self.assertFalse(r["ok"])
        self.assertTrue(any("NBCAL" in m for m in r["motivos"]))

    def test_nbcal_no_fim_de_nome_longo_tambem_barra(self):  # 44a rodada: o exemplo do Codex
        longo = ("https://shopee.com.br/Kit-Enxoval-Bebe-Completo-Presente-Maternidade-Menino-Menina-Rosa-Azul-"
                 "Conjunto-Infantil-com-Mamadeira-i.55.111")
        r = montar_postagem(CURTO, "29,90", CFG, abrir=abridor(longo))
        self.assertFalse(r["ok"])
        self.assertNotIn("mensagem", r)
        self.assertTrue(any("NBCAL" in m for m in r["motivos"]), r["motivos"])
        for tamanho in (50, 100, 200, 400):  # a palavra proibida sempre no FIM
            enchimento = "-".join(["Conjunto"] * (tamanho // 9))
            url = f"https://shopee.com.br/Kit-{enchimento}-Chupeta-i.55.111"
            r = montar_postagem(CURTO, "29,90", CFG, abrir=abridor(url))
            self.assertFalse(r["ok"], tamanho)
            r = montar_postagem(CURTO, "29,90", CFG, nome_digitado=f"Kit {enchimento.replace('-', ' ')} Mamadeira",
                                abrir=abridor(ALMOFADA))
            self.assertFalse(r["ok"], tamanho)
            self.assertNotIn("mensagem", r)

    def test_nbcal_grudado_em_numero_ou_palavra_barra(self):  # 45a rodada
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for nome in ("Kit Enxoval Mamadeira260ml", "KitMamadeira", "MAMADEIRAANTICOLICA", "Chupeta3pcs",
                     "260mlMamadeira Bebe", "Kit Enxoval com fórmulainfantil", "Mamadeiras Kit", "chupetinha? Chupeta2un",
                     "Bico260ml mamadeira", "LeiteEmPo Infantil", "papinha8m"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        for nome in ("Armário Organizador de Cozinha", "Presilha Bico de Pato Cabelo", "Toalha Bicolor de Banho",
                     "Almofada de Amamentação", "Body Bebê Algodão 3 Peças", "Organizador de Remédios Semanal"):
            if "Remédios" in nome:
                continue  # 'remedio' e proibido de proposito (venda controlada)
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)

    def test_propriedade_palavra_nbcal_sempre_barra(self):  # qualquer cola em volta
        import random
        from robo.curadoria import verificar_bloqueio
        rnd = random.Random(45)
        termos = ["mamadeira", "chupeta", "papinha", "formula infantil", "leite em po", "aptamil", "chuquinha"]
        colas = ["", " ", "-", "_", "260ml", "3", "Kit", "KIT ", "Anticolica", "+", "2un", "(", ")"]
        for _ in range(2000):
            termo = rnd.choice(termos)
            grafia = "".join(ch.upper() if rnd.random() < .5 else ch for ch in termo)
            if rnd.random() < .5:
                grafia = grafia.replace(" ", rnd.choice(["", "-", " "]))
            nome = rnd.choice(colas) + rnd.choice(colas) + grafia + rnd.choice(colas) + rnd.choice(colas)
            self.assertIsNotNone(verificar_bloqueio(nome, CFG["bloqueios"], CFG.get("bloqueios_combinados")), nome)

    def test_exemplos_da_46a_e_bico_grudado(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for nome in ("Kit BicoSilicone Infantil", "KitCoposDeTransicao Bebe Infantil", "copostransicao",
                     "Fórmulas Infantis", "bicodemamadeira", "BICO SILICONE BEBE", "protetoresmamilo", "copocombico"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        for nome in ("Body Bebe Estampa Pinhas", "Toalha Bicolor Infantil", "Lápis de Cor Infantis",
                     "Copo Térmico Infantil", "Kit Pinhas Natal"):
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)

    def test_exemplos_da_47a(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for nome in ("Chupetinha silicone bebe", "Kit bicoslatex infantil", "Mamadeirinha Anticólica", "KitChupetas",
                     "Chuquinhas Bebe", "Bico Ortodontico Bebe", "bicodesilicone infantil", "Bicos de Silicone Bebe",
                     "Papinhas Organicas"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        for nome in ("Saco de Confeitar com Bico de Silicone", "Kit Bicos de Confeitar Inox", "Bico de Confeitaria"):
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)
        r = montar_postagem(CURTO, "29,90", CFG, abrir=abridor("https://shopee.com.br/Chupetinha-silicone-bebe-i.55.111"))
        self.assertFalse(r["ok"])

    def test_exemplos_da_48a(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for nome in ("Kitbicos silicone bebe", "Biquinho de silicone bebe", "Kit Biquinhos Latex Infantil",
                     "Bolsa Térmica Porta Mamadeira com 2 Mamadeiras", "kitbicosilicone", "Bico Infantil Silicone"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        for nome in ("Bolsa termica porta mamadeirinhas", "Porta Mamadeira Térmico", "Escova de Mamadeira Limpeza",
                     "Secador de Mamadeiras", "Suporte para Mamadeira", "Portamamadeira Bebe",
                     "Toalha Bicolor Infantil", "Saco de Confeitar com Bico de Silicone"):
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)

    def test_exemplos_da_49a(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        avent = "Kit 2 Bicos Philips Avent Pétala Natural Response Fluxo 2 Lento"
        for nome in (avent, "Kit Bolsa Térmica Porta Mamadeira com Bico", "Bico NUK Tamanho 1", "Bicos Fluxo Lento"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        for nome in ("Presilha Bico de Pato para Bebê", "Escorredor de Mamadeiras Bebê", "Cesto para Mamadeiras"):
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)
        url = "https://shopee.com.br/Kit-2-Bicos-Philips-Avent-Petala-Natural-Response-Fluxo-2-Lento-i.55.111"
        self.assertFalse(montar_postagem(CURTO, "29,90", CFG, abrir=abridor(url))["ok"])

    def test_exemplos_da_50a(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for nome in ("Protetor de Seios com 2 Unidades Tam2 - MAM", "Protetores de Seio Silicone",
                     "ProtetorDeSeio", "Escova de Mamadeira com Bico de Silicone Bebe Mamadeira Inclusa"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        for nome in ("Escova para Mamadeira e Bico Limpeza", "Escova de Mamadeiras e Bicos", "Secador de Mamadeira e Bico",
                     "Absorvente de Seio Lavável"):
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Protetor de Seios com 2 Unidades Tam2 - MAM",
                            abrir=abridor(SEM_NOME))
        self.assertFalse(r["ok"])

    def test_exemplos_da_51a(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for nome in ("Protetor de Silicone para Seios 2 peças Multikids Baby - BB191",
                     "Copo Trainer 220 ml Copo de Treinamento do Bebê MAM", "Protetor Mamilo Silicone"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
            r = montar_postagem(CURTO, "29,90", CFG, nome_digitado=nome, abrir=abridor(SEM_NOME))
            self.assertFalse(r["ok"], nome)
        for nome in ("Kit Escova de Limpeza para Mamadeiras e Bico 2 em 1 nas cores Azul / Vermelha - Buba",
                     "Copo Térmico Inox 500ml", "Protetor de Colchão Impermeável", "Absorvente de Seio Lavável"):
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)

    def test_exemplos_da_53a(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        caneca = "Caneca de Treinamento Infantil com Alças e Tampa Pasútil– 280 ml ou 330 ml"
        for tag in ("cozinha", "casa", "feminino", "limpeza", "bebe", "maternidade"):
            for nome in (caneca, "Copo Infantil Kids Dinossauro", "Garrafinha Bebê Squeeze"):
                r = montar_postagem(CURTO, "29,90", CFG, nome_digitado=nome, tag=tag, abrir=abridor(SEM_NOME),
                                    confirmado=True)
                self.assertFalse(r["ok"], (nome, tag))
        self.assertIsNone(verificar_bloqueio("Protetor de Seios Adesivo Silicone Reutilizável Miniso", b, comb))
        for nome in ("Protetor de Mamilo Silicone Amamentação", "Protetor de Seios para Amamentação 2 Unidades MAM",
                     "Protetor Mamilar Silicone"):
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Copo Térmico Inox Café", tag="cozinha",
                            abrir=abridor(SEM_NOME))
        self.assertFalse(any(m.startswith("Produto:") for m in r["motivos"]), r["motivos"])

    def test_bebe_e_maternidade_exigem_confirmacao(self):  # 52a: a ultima camada e a pessoa
        for tag in ("bebe", "maternidade"):
            r = montar_postagem(CURTO, "39,90", CFG, tag=tag, abrir=abridor(ALMOFADA))
            self.assertFalse(r["ok"])
            self.assertTrue(any(m.startswith("Confirmação:") for m in r["motivos"]))
            self.assertNotIn("mensagem", r)
            r = montar_postagem(CURTO, "39,90", CFG, tag=tag, abrir=abridor(ALMOFADA), confirmado=True)
            self.assertTrue(r["ok"], r["motivos"])
            r = montar_postagem(CURTO, "39,90", CFG, tag=tag, abrir=abridor(ALMOFADA), confirmado="sim")
            self.assertFalse(r["ok"])  # so True de verdade conta
        # a confirmacao NUNCA livra as travas automaticas
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Kit Mamadeira Anticólica", abrir=abridor(SEM_NOME),
                            confirmado=True)
        self.assertFalse(r["ok"])
        # registro salvo sem a confirmacao nao aparece como pronto, mesmo assinado - em QUALQUER tag
        r = montar_postagem(CURTO, "39,90", CFG, tag="casa", abrir=abridor(ALMOFADA), confirmado=True)
        self.assertTrue(r["ok"], r["motivos"])
        for tag in ("casa", "maternidade", "cozinha"):
            falso = {**r, "tag": tag, "confirmado_nbcal": False}
            falso["assinatura"] = assinatura(falso)
            self.assertFalse(POSTAGEM.registro_confiavel(falso, CFG), tag)

    def test_escova_com_mamadeira_e_kit_com_mamadeira(self):  # 55a (risco)
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for nome in ("Kit Escova com Mamadeira e Bico", "Escova com Mamadeira Inclusa", "Kit Mamadeira e Escova",
                     "Kit Escova + Mamadeira e Bico Silicone Bebê", "Escova & Mamadeira", "Escova Kit Mamadeira",
                     "Escova e Mamadeira 260ml"):  # 57a
            self.assertIsNotNone(verificar_bloqueio(nome, b, comb), nome)
        for nome in ("Escova de Mamadeira", "Escova para Mamadeira e Bico", "Kit Escova de Limpeza para Mamadeiras e Bico",
                     "Escova Giratória para Mamadeiras", "Secador de Mamadeira e Bico",
                     "Escova de Limpeza Mamadeira Bebê", "Escova Mamadeira e Bico Silicone Bebê",  # 56a
                     "Escova Dupla para Mamadeira e Bico Bebê", "Escova 2 em 1 para Mamadeiras"):  # 57a
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)

    def test_confirmacao_em_toda_tag(self):  # 54a: o copo de transicao real sem palavra de bebe
        for tag in ("casa", "feminino", "cozinha", "limpeza", "bebe", "maternidade"):
            r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Copo Rosa", tag=tag, abrir=abridor(SEM_NOME))
            self.assertFalse(r["ok"], tag)
            self.assertTrue(any(m.startswith("Confirmação:") for m in r["motivos"]), tag)
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="COPO MAGICO 360 COALA - 2947 - CLINGO", tag="cozinha",
                            abrir=abridor(SEM_NOME), confirmado=True)
        self.assertFalse(r["ok"])  # a marca de alimentacao infantil barra mesmo confirmado

    def test_exemplos_da_52a(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        caneca = "Caneca Lillo Antivazamento Aprendizado Magia Azul 207ml"
        nuk = "Copo Antivazamento Active Cup First Choice 300ml NUK - Rosa"
        for nome in (caneca, nuk):
            for tag in ("bebe", "maternidade", "cozinha", "casa", "feminino", "limpeza"):  # trocar a tag nao livra
                r = montar_postagem(CURTO, "29,90", CFG, nome_digitado=nome, tag=tag, abrir=abridor(SEM_NOME))
                self.assertFalse(r["ok"], (nome, tag))
        self.assertIsNone(verificar_bloqueio("Protetor Adesivo De Silicone Para Seios Invisível Reutilizável", b, comb))
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Protetor Adesivo De Silicone Para Seios Invisível",
                            tag="feminino", abrir=abridor(SEM_NOME))
        self.assertFalse(any(m.startswith("Produto:") for m in r["motivos"]), r["motivos"])
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Copo Térmico Inox Café", tag="cozinha", abrir=abridor(SEM_NOME))
        self.assertFalse(any(m.startswith("Produto:") for m in r["motivos"]), r["motivos"])

    def test_trava_por_raiz_no_manual_de_bebe_e_maternidade(self):  # 51a
        for nome in ("Copo Infantil Alça Rosa", "Kit Alimentador Fruta", "Mingau Pronto", "Leite Infantil",
                     "Conchas Seio Silicone", "Caneca Transição Bebê"):
            for tag in ("bebe", "maternidade"):
                r = montar_postagem(CURTO, "19,90", CFG, nome_digitado=nome, tag=tag, abrir=abridor(SEM_NOME))
                self.assertFalse(r["ok"], (nome, tag))
        for nome in ("Almofada de Amamentação Macia", "Absorvente de Seio Lavável", "Body Bebê Algodão",
                     "Bolsa Maternidade Mochila", "Toalha de Banho Bebê", "Escova de Mamadeira Limpeza"):
            r = montar_postagem(CURTO, "19,90", CFG, nome_digitado=nome, tag="bebe", abrir=abridor(SEM_NOME))
            self.assertFalse(any(m.startswith("Produto:") for m in r["motivos"]), (nome, r["motivos"]))
        # fora de bebe/maternidade a trava por raiz nao vale (copo termico de cozinha)
        r = montar_postagem(CURTO, "19,90", CFG, nome_digitado="Copo Térmico Inox", tag="cozinha", abrir=abridor(SEM_NOME))
        self.assertFalse(any(m.startswith("Produto:") for m in r["motivos"]), r["motivos"])

    def test_trava_rigida_do_manual_barra_qualquer_bico(self):  # 49a: sem contexto tambem
        for nome in ("Kit 2 Bicos Tamanho M", "Biquinho Universal", "KitBicos"):
            r = montar_postagem(CURTO, "19,90", CFG, nome_digitado=nome, abrir=abridor(SEM_NOME))
            self.assertFalse(r["ok"], nome)
        for nome in ("Presilha Bico de Pato Bebê", "Toalha Bicolor Bebê", "Kit Bicos de Confeitar"):
            r = montar_postagem(CURTO, "19,90", CFG, nome_digitado=nome, abrir=abridor(SEM_NOME))
            self.assertFalse(any(m.startswith("Produto:") for m in r["motivos"]), (nome, r["motivos"]))

    def test_propriedade_diminutivo_e_aumentativo(self):
        from robo.curadoria import verificar_bloqueio
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        for raiz_ in ("mamadeir", "chupet", "chuquinh", "papinh"):
            for fim in ("a", "as", "inha", "inhas", "ao", "oes", "ona", "zinha"):
                for forma in (f"Kit {raiz_}{fim} Bebe", f"kit{raiz_}{fim}", f"{raiz_.upper()}{fim.upper()}3un"):
                    self.assertIsNotNone(verificar_bloqueio(forma, b, comb), forma)

    def test_propriedade_todo_termo_nbcal_do_config_em_qualquer_grafia(self):
        import random
        from robo.curadoria import verificar_bloqueio
        rnd = random.Random(46)
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        vizinhos = ["Kit", "Bebe", "Infantil", "260ml", "3", "Rosa", "Premium", "Anticolica", ""]
        for termo in b["nbcal"]:
            palavras = termo.split()
            for _ in range(60):
                conectores = {"de", "do", "da", "com", "em", "para"}
                ps = [p + ("s" if rnd.random() < .3 and len(p) > 2 and p not in conectores else "") for p in palavras]
                ps = [p.upper() if rnd.random() < .3 else (p.capitalize() if rnd.random() < .5 else p) for p in ps]
                juncao = rnd.choice([" ", "", "-", "_"])
                grafia = juncao.join(ps)
                if rnd.random() < .3:  # grudado num vizinho, sem separar
                    if len(termo.replace(" ", "")) < 6:
                        continue  # limite de proposito: termo curto so inteiro ('chuca' x 'machucado')
                    grafia = rnd.choice(vizinhos).lower() + grafia.lower()
                nome = f"{rnd.choice(vizinhos)} {grafia}{rnd.choice(['', '260ml', '3un', ' '])} {rnd.choice(vizinhos)}"
                self.assertIsNotNone(verificar_bloqueio(nome, b, comb), (termo, nome))

    def test_nomes_bons_do_nicho_nao_sao_barrados(self):
        from robo.curadoria import verificar_bloqueio
        from robo.demo import BUSCAS_DEMO, ClienteDemo  # noqa: F401
        b, comb = CFG["bloqueios"], CFG.get("bloqueios_combinados")
        bons = ["Almofada de Amamentação Macia", "Body Bebê Algodão Estampa Pinhas", "Bolsa Maternidade Mochila",
                "Toalha de Banho Bebê com Capuz", "Kit Organizador de Geladeira", "Pijama Feminino Cetim",
                "Jogo de Espátulas de Silicone", "Mop Giratório Balde", "Sutiã de Amamentação", "Lápis Infantis",
                "Toalha Bicolor", "Presilha Bico de Pato", "Copo Térmico Inox", "Armário Organizador",
                "Absorvente de Seio Lavável", "Travesseiro de Amamentação", "Babador Bandana Infantil"]
        for nome in bons:
            self.assertIsNone(verificar_bloqueio(nome, b, comb), nome)

    def test_mensagem_de_produto_grudado_nao_sai(self):  # o caminho exato da 45a
        url = "https://shopee.com.br/Kit-Enxoval-Mamadeira260ml-i.55.111"
        r = montar_postagem(CURTO, "29,90", CFG, abrir=abridor(url))
        self.assertFalse(r["ok"])
        self.assertNotIn("mensagem", r)

    def test_preco_longo_e_lido_inteiro(self):  # 45a rodada: cortar mudava R$ 100,99 para R$ 100,00
        self.assertEqual(ler_preco("0" * 17 + "100,99"), 100.99)

    def test_nome_digitado_longo_demais_e_recusado_nao_cortado(self):
        r = montar_postagem(CURTO, "29,90", CFG, nome_digitado="Almofada " * 30, abrir=abridor(SEM_NOME))
        self.assertFalse(r["ok"])
        self.assertTrue(any("150 caracteres" in m for m in r["motivos"]))

    def test_link_sem_marcacao_ou_quebrado_nao_monta(self):
        def direto(url, timeout):
            return 200, None
        r = montar_postagem(ALMOFADA, "29,90", CFG, abrir=direto)  # link direto do produto
        self.assertFalse(r["ok"])
        self.assertTrue(r["motivos"][0].startswith("Link:"))
        r = montar_postagem(CURTO, "29,90", CFG, abrir=lambda u, t: (301, "https://shope.ee/error_page"))
        self.assertFalse(r["ok"])
        r = montar_postagem("https://golpe.exemplo/x", "29,90", CFG, abrir=direto)
        self.assertFalse(r["ok"])

    def test_preco_invalido_nao_monta(self):
        r = montar_postagem(CURTO, "barato", CFG, abrir=abridor(ALMOFADA))
        self.assertFalse(r["ok"])
        self.assertTrue(any(m.startswith("Preço:") for m in r["motivos"]))

    def test_sem_nome_no_endereco_pede_o_nome_e_usa_o_digitado(self):
        r = montar_postagem(CURTO, "19,90", CFG, abrir=abridor(SEM_NOME))
        self.assertFalse(r["ok"])
        self.assertTrue(any(m.startswith("Nome:") for m in r["motivos"]))
        r = montar_postagem(CURTO, "19,90", CFG, nome_digitado="Almofada de Amamentação", abrir=abridor(SEM_NOME),
                            confirmado=True)
        self.assertTrue(r["ok"], r["motivos"])
        self.assertIn("Almofada", r["mensagem"])

    def test_nome_com_promessa_do_vendedor_e_limpo(self):
        r = montar_postagem(CURTO, "19,90", CFG, nome_digitado="Almofada de Amamentação 70% OFF Frete Grátis 2x1",
                            abrir=abridor(SEM_NOME), confirmado=True)
        self.assertTrue(r["ok"], r["motivos"])
        for proibido in ("70", "%", "OFF", "Frete", "2x1"):
            self.assertNotIn(proibido, r["mensagem"].splitlines()[1])

    def test_tag_estranha_cai_em_maternidade(self):
        r = montar_postagem(CURTO, "19,90", CFG, tag="<script>", abrir=abridor(ALMOFADA))
        self.assertEqual(r["tag"], "maternidade")


class TestComandoPostagem(unittest.TestCase):
    def rodar(self, argv):
        import robo.__main__ as M
        with tempfile.TemporaryDirectory() as tmp:
            antes, M.PASTA_SAIDA = M.PASTA_SAIDA, Path(tmp)
            try:
                saida = io.StringIO()
                with redirect_stdout(saida):
                    codigo = M.cmd_postagem(argv, abrir=abridor(ALMOFADA))
                arq = Path(tmp) / "postagens.json"
                dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else None
            finally:
                M.PASTA_SAIDA = antes
        return codigo, saida.getvalue(), dados

    def test_grava_para_a_tela(self):
        codigo, texto, dados = self.rodar(["--link", CURTO, "--preco", "39,90", "--confirmo", "nao-e-nbcal"])
        self.assertEqual(codigo, 0)
        self.assertIn("MENSAGEM PRONTA", texto)
        self.assertEqual(dados["versao"], 2)
        self.assertTrue(dados["postagens"][0]["ok"])

    def test_argumentos_errados(self):
        for argv in ([], ["--link", CURTO], ["--preco", "1"], ["--link", CURTO, "--preco"],
                     ["--link", CURTO, "--preco", "1", "--outro", "x"], ["--link", CURTO, "--link", CURTO, "--preco", "1"]):
            codigo, _, dados = self.rodar(argv)
            self.assertEqual((codigo, dados), (1, None), argv)


class TestTelaPostagem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import robo.painel as P
        cls.P = P
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saida_antes, P.SAIDA = P.SAIDA, Path(cls.tmp.name)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), P._Handler)
        cls.porta = cls.srv.server_address[1]
        cls.porta_antes, P.PORTA = P.PORTA, cls.porta
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.P.SAIDA, cls.P.PORTA = cls.saida_antes, cls.porta_antes
        cls.tmp.cleanup()

    def setUp(self):
        self.chamadas = []
        self.executar_antes = self.P._executar
        self.P._executar = lambda nome, args=None: self.chamadas.append((nome, args))
        self.P._estado.update(rodando=None, aviso_postagem="")

    def tearDown(self):
        self.P._executar = self.executar_antes
        self.P._estado.update(rodando=None, aviso_postagem="")
        (Path(self.tmp.name) / "postagens.json").unlink(missing_ok=True)

    def post(self, campos: dict, origem=True):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        if origem:
            h["Origin"] = f"http://127.0.0.1:{self.porta}"
        c.request("POST", "/postagem", body=urlencode(campos).encode(), headers=h)
        r = c.getresponse()
        r.read()
        time.sleep(0.4)
        return r.status, r.getheader("Location")

    def test_formulario_vira_comando_sem_shell(self):
        status, destino = self.post({"link": f" {CURTO} ", "preco": "39,90", "nome": "Almofada", "tag": "bebe"})
        self.assertEqual((status, destino), (303, "/?aba=postagem"))
        self.assertEqual(self.chamadas, [("postagem", ["postagem", "--link", CURTO, "--preco", "39,90",
                                                       "--tag", "bebe", "--nome", "Almofada"])])
        self.chamadas.clear()
        self.P._estado["rodando"] = None
        self.post({"link": CURTO, "preco": "39,90", "tag": "bebe", "confirmo": "nao-e-nbcal"})
        self.assertEqual(self.chamadas[0][1][-2:], ["--confirmo", "nao-e-nbcal"])
        self.chamadas.clear()
        self.P._estado["rodando"] = None
        self.post({"link": CURTO, "preco": "39,90", "tag": "bebe", "confirmo": "on"})  # valor estranho nao confirma
        self.assertNotIn("--confirmo", self.chamadas[0][1])

    def test_sem_link_ou_sem_preco_so_avisa(self):
        self.post({"link": "nada", "preco": "1"})
        self.assertIn("Cole o link", self.P._estado["aviso_postagem"])
        self.post({"link": CURTO, "preco": ""})
        self.assertIn("Digite o preço", self.P._estado["aviso_postagem"])
        self.post({"link": CURTO, "preco": "1", "nome": "Kit " + "a " * 100 + "Mamadeira"})  # 44a rodada
        self.assertIn("150 caracteres", self.P._estado["aviso_postagem"])
        self.post({"link": CURTO, "preco": "0" * 17 + "100,99"})  # 45a: nunca cortar o preco
        self.assertIn("Digite o preço", self.P._estado["aviso_postagem"])
        self.assertEqual(self.chamadas, [])

    def test_post_de_outro_site_e_recusado(self):
        status, _ = self.post({"link": CURTO, "preco": "1"}, origem=False)
        self.assertEqual(status, 403)
        self.assertEqual(self.chamadas, [])

    def _gravar(self, postagens):
        (Path(self.tmp.name) / "postagens.json").write_text(json.dumps({"versao": 2, "postagens": postagens}),
                                                            encoding="utf-8")

    def _bom(self):
        bom = montar_postagem(CURTO, "39,90", CFG, abrir=abridor(ALMOFADA), confirmado=True)
        self.assertTrue(bom["ok"])
        bom["quando"] = "2026-10-26T10:00:00"
        bom["assinatura"] = assinatura(bom)
        return bom

    def test_registro_verdadeiro_aparece_pronto(self):
        bom = self._bom()
        self._gravar([bom])
        pagina = self.P._pagina("demo")
        self.assertIn("Copiar mensagem</button>", pagina.split('id="postagem"')[1].split('id="conferir"')[0])
        self.assertIn("R$ 39,90", pagina)
        self.assertIn(f'href="{CURTO}"', pagina)

    def test_registro_adulterado_nao_vira_mensagem_pronta(self):  # 46a-48a rodadas
        bom = self._bom()

        def remontado(**troca):  # adulteracao CONSISTENTE: as duas mensagens remontadas
            r = {**bom, **troca}
            r["mensagem"], r["mensagem_feed"] = mensagens(r["emoji"], r["nome"], r["preco"], r["link"])
            return r
        adulterados = [
            remontado(emoji="De R$ 99,90 - 60% OFF Frete Gratis"),            # 48a
            remontado(link="https://shopee.com.br/buyer/login"),               # 48a
            remontado(preco=0.5),                                              # 48a
            {**bom, "assinatura": "0" * 64}, {k: v for k, v in bom.items() if k != "assinatura"},{**bom, "mensagem": bom["mensagem"] + "\nDe R$ 99,90"},          # mensagem trocada
                       {**bom, "nome": "Kit Mamadeira", "mensagem": "x"},               # NBCAL
                       {**bom, "afiliado": None}, {**bom, "link": "javascript:alert(1)"},
                       {**bom, "preco": 0}, {**bom, "preco": True},
                       # 47a rodada: adulteracao CONSISTENTE (mensagens remontadas com os campos falsos)
                       {**bom, "nome": "De R$ 99,90 - 60% OFF Frete Gratis",
                        "mensagem": __import__("robo.postagem", fromlist=["x"]).mensagens(
                            bom["emoji"], "De R$ 99,90 - 60% OFF Frete Gratis", bom["preco"], bom["link"])[0]},
                       {**bom, "link": "https://shope.ee/error_page", "afiliado": "an_123"},
                       {"ok": True, "nome": "<script>x</script>", "mensagem": "<b>oi</b>", "link": CURTO}]
        for adulterado in adulterados:
            self._gravar([adulterado])
            secao = self.P._pagina("demo").split('id="postagem"')[1].split('id="conferir"')[0]
            self.assertNotIn("Copiar mensagem</button>", secao, adulterado)
            self.assertIn("Registro não confere", secao)
            for cru in ("<script>x", "<b>oi", 'href="javascript:'):
                self.assertNotIn(cru, secao)

    def test_resultado_com_erro_escapado(self):
        self._gravar([{"ok": False, "motivos": ["<img src=x onerror=alert(1)>"], "link": "javascript:alert(1)",
                       "quando": "x"}, "lixo"])
        pagina = self.P._pagina("demo")
        self.assertIn('id="postagem"', pagina)
        self.assertNotIn("<img src=x", pagina)
        self.assertNotIn('href="javascript:', pagina)

    def test_versao_antiga_ou_arquivo_estragado_nao_aparece(self):
        (Path(self.tmp.name) / "postagens.json").write_text(json.dumps({"postagens": [{"ok": True, "nome": "VELHA",
                                                                                     "mensagem": "m"}]}), encoding="utf-8")
        self.assertNotIn("VELHA", self.P._pagina("demo"))
        # 45a rodada: as da versao 1 (antes da correcao do bloqueio NBCAL) tambem nao aparecem
        (Path(self.tmp.name) / "postagens.json").write_text(json.dumps({"versao": 1, "postagens": [
            {"ok": True, "nome": "VERSAO1", "mensagem": "m", "link": CURTO}]}), encoding="utf-8")
        self.assertNotIn("VERSAO1", self.P._pagina("demo"))
        (Path(self.tmp.name) / "postagens.json").write_text("{quebrado", encoding="utf-8")
        self.assertIn('id="postagem"', self.P._pagina("demo"))


if __name__ == "__main__":
    unittest.main()
