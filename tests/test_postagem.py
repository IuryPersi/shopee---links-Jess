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
from robo.postagem import ler_preco, montar_postagem  # noqa: E402

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
        r = montar_postagem(CURTO, "39,90", CFG, abrir=abridor(ALMOFADA))
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
        r = montar_postagem(CURTO, "19,90", CFG, nome_digitado="Almofada de Amamentação", abrir=abridor(SEM_NOME))
        self.assertTrue(r["ok"], r["motivos"])
        self.assertIn("Almofada", r["mensagem"])

    def test_nome_com_promessa_do_vendedor_e_limpo(self):
        r = montar_postagem(CURTO, "19,90", CFG, nome_digitado="Almofada de Amamentação 70% OFF Frete Grátis 2x1",
                            abrir=abridor(SEM_NOME))
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
        codigo, texto, dados = self.rodar(["--link", CURTO, "--preco", "39,90"])
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

    def test_resultado_na_tela_escapado(self):
        postagens = [
            {"ok": True, "emoji": "🤰", "nome": "<script>x</script>", "preco": 39.9, "link": CURTO,
             "mensagem": "#publi\n<b>oi</b>", "mensagem_feed": "f", "avisos": ["<i>a</i>"], "quando": "2026-10-26T10:00:00"},
            {"ok": False, "motivos": ["<img src=x onerror=alert(1)>"], "link": "javascript:alert(1)", "quando": "x"},
            {"ok": True, "nome": "sem mensagem"}, "lixo"]
        (Path(self.tmp.name) / "postagens.json").write_text(json.dumps({"versao": 2, "postagens": postagens}),
                                                            encoding="utf-8")
        pagina = self.P._pagina("demo")
        self.assertIn('id="postagem"', pagina)
        for cru in ("<script>x", "<b>oi", "<i>a", "<img src=x", 'href="javascript:'):
            self.assertNotIn(cru, pagina)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", pagina)
        self.assertIn(f'href="{CURTO}"', pagina)
        self.assertIn("R$ 39,90", pagina)

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
