"""'Conferir links': links colados a mao (gerados no painel de afiliados). Respostas FALSAS, sem internet."""
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
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from robo.links import (examinar_link, links_do_texto, marca_de_afiliado, nivel_do_exame,  # noqa: E402
                        nome_da_pagina, produto_da_pagina, texto_do_exame)

CURTO = "https://s.shopee.com.br/AbC123"
SLUG = "https://shopee.com.br/Garrafa-T%C3%A9rmica-Inox-1L-i.55.987654"
MARCA = "?utm_medium=affiliates&utm_source=an_10000000001&utm_content=-"


def abridor(respostas: dict):
    """url -> (status, location). URL nao listada = erro de rede."""
    def abrir(url, timeout):
        if url not in respostas:
            raise OSError("sem rede")
        return respostas[url]
    return abrir


class TestLinksDoTexto(unittest.TestCase):
    def test_tira_os_links_de_uma_mensagem(self):
        texto = f"Olha: {CURTO}, e (https://s.shopee.com.br/XyZ). Valeu!\n{CURTO}"
        self.assertEqual(links_do_texto(texto), [CURTO, "https://s.shopee.com.br/XyZ"])

    def test_completa_https_so_para_a_shopee(self):
        self.assertEqual(links_do_texto("s.shopee.com.br/AbC shope.ee/x shopee.com.br/product/1/2"),
                         ["https://s.shopee.com.br/AbC", "https://shope.ee/x", "https://shopee.com.br/product/1/2"])
        self.assertEqual(links_do_texto("http://s.shopee.com.br/x"), ["https://s.shopee.com.br/x"])
        self.assertEqual(links_do_texto("http://golpe.exemplo/x"), ["http://golpe.exemplo/x"])  # vira 'quebrado'

    def test_ignora_o_que_nao_e_link_e_respeita_o_limite(self):
        self.assertEqual(links_do_texto("oi tudo bem javascript:alert(1) golpe.exemplo/x"), [])
        self.assertEqual(links_do_texto(""), [])
        self.assertEqual(links_do_texto(None), [])
        muitos = " ".join(f"https://s.shopee.com.br/L{i}" for i in range(30))
        self.assertEqual(len(links_do_texto(muitos)), 20)
        self.assertEqual(links_do_texto("https://s.shopee.com.br/" + "a" * 700), [])


class TestPaginaDoProduto(unittest.TestCase):
    def test_loja_item_e_nome(self):
        self.assertEqual(produto_da_pagina(SLUG), (55, 987654))
        self.assertEqual(nome_da_pagina(SLUG), "Garrafa Térmica Inox 1L")
        self.assertEqual(produto_da_pagina("https://shopee.com.br/product/55/987654"), (55, 987654))
        self.assertIsNone(nome_da_pagina("https://shopee.com.br/product/55/987654"))
        self.assertIsNone(produto_da_pagina("https://shopee.com.br/m/vem-ai-dia-de-cupons"))

    def test_nome_sem_caractere_de_controle_e_curto(self):
        self.assertEqual(nome_da_pagina("https://shopee.com.br/A%0Ab%07c-i.55.987654"), "A b c")
        self.assertEqual(len(nome_da_pagina("https://shopee.com.br/" + "Ab-" * 80 + "x-i.55.987654")), 90)


class TestMarcaDeAfiliado(unittest.TestCase):
    def test_marcacao(self):
        self.assertEqual(marca_de_afiliado([SLUG + MARCA]), "an_10000000001")
        self.assertEqual(marca_de_afiliado([SLUG + "?utm_medium=Affiliates&utm_source=an_7"]), "an_7")
        self.assertEqual(marca_de_afiliado([SLUG + "?utm_medium=affiliates"]), "sim")
        self.assertEqual(marca_de_afiliado([SLUG + "?utm_medium=affiliates&utm_source=an_7x"]), "sim")
        self.assertIsNone(marca_de_afiliado([SLUG + "?utm_source=an_7"]))  # sem utm_medium nao conta
        self.assertIsNone(marca_de_afiliado([SLUG]))
        self.assertIsNone(marca_de_afiliado([]))


class TestExaminarLink(unittest.TestCase):
    def test_link_de_afiliado_que_abre_o_produto(self):
        r = examinar_link(CURTO, abrir=abridor({CURTO: (301, SLUG + MARCA), SLUG + MARCA: (200, None)}))
        self.assertEqual((r["estado"], r["loja"], r["item"], r["afiliado"]), ("produto", 55, 987654, "an_10000000001"))
        self.assertEqual(r["nome"], "Garrafa Térmica Inox 1L")
        self.assertEqual(nivel_do_exame(r), "ok")
        self.assertIn("com a marcação de afiliado an_10000000001", texto_do_exame(r))
        self.assertEqual(r["trilha"], [f"301 s.shopee.com.br/AbC123", "200 shopee.com.br/Garrafa-T%C3%A9rmica-Inox-1L-i.55.987654"])
        self.assertNotIn("utm", json.dumps(r["trilha"]))  # a trilha nao leva os parametros

    def test_link_direto_do_produto_avisa_que_nao_rende_comissao(self):
        r = examinar_link(SLUG, abrir=abridor({SLUG: (200, None)}))
        self.assertEqual((r["estado"], r["afiliado"], nivel_do_exame(r)), ("produto", None, "aviso"))
        self.assertIn("não achei a marcação de afiliado", texto_do_exame(r))

    def test_pagina_que_nao_e_de_produto(self):
        campanha = "https://shopee.com.br/m/vem-ai-dia-de-cupons" + MARCA
        r = examinar_link(CURTO, abrir=abridor({CURTO: (301, campanha), campanha: (200, None)}))
        self.assertEqual((r["estado"], nivel_do_exame(r)), ("outra_pagina", "aviso"))
        self.assertIn("não numa página de produto", texto_do_exame(r))
        self.assertIn("Tem a marcação de afiliado", texto_do_exame(r))
        self.assertIsNone(r["item"])

    def test_link_inexistente_e_rede_e_fora_da_shopee(self):
        r = examinar_link(CURTO, abrir=abridor({CURTO: (301, "https://shope.ee/error_page")}))
        self.assertEqual((r["estado"], nivel_do_exame(r)), ("quebrado", "erro"))
        self.assertIn("link inexistente ou expirado", texto_do_exame(r))
        r = examinar_link(CURTO, abrir=abridor({}))
        self.assertEqual((r["estado"], nivel_do_exame(r)), ("sem_resposta", "espera"))
        chamadas = []
        r = examinar_link("https://golpe.exemplo/x", abrir=lambda u, t: chamadas.append(u))
        self.assertEqual(r["estado"], "quebrado")
        self.assertIn("não é um link da Shopee", texto_do_exame(r))
        self.assertEqual(chamadas, [])  # nem tentou abrir fora da Shopee

    def test_link_que_trava_tem_prazo(self):
        liberar = threading.Event()

        def travado(url, timeout):
            liberar.wait(10)
            return 200, None
        inicio = time.monotonic()
        try:
            r = examinar_link(CURTO, abrir=travado, prazo_total=0.2, folga=0.1)
        finally:
            liberar.set()
        self.assertEqual(r["estado"], "sem_resposta")
        self.assertLess(time.monotonic() - inicio, 2)

    def test_texto_nao_quebra_com_resultado_incompleto(self):
        for r in ({}, {"estado": "produto"}, {"estado": "outra_pagina"}, {"estado": "quebrado"}, {"estado": "x"}):
            self.assertIsInstance(texto_do_exame(r), str)
            self.assertIn(nivel_do_exame(r), ("ok", "aviso", "erro", "espera"))


class TestComandoConferir(unittest.TestCase):
    def rodar(self, argv, abrir):
        import robo.__main__ as M
        with tempfile.TemporaryDirectory() as tmp:
            antes, M.PASTA_SAIDA = M.PASTA_SAIDA, Path(tmp)
            saida = io.StringIO()
            try:
                with redirect_stdout(saida):
                    codigo = M.cmd_conferir(argv, abrir=abrir, pausa=0)
                arq = Path(tmp) / "conferencia.json"
                dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else None
            finally:
                M.PASTA_SAIDA = antes
        return codigo, saida.getvalue(), dados

    def test_confere_e_grava_para_a_tela(self):
        r = abridor({CURTO: (301, SLUG + MARCA), SLUG + MARCA: (200, None)})
        codigo, texto, dados = self.rodar([f"veja {CURTO} e https://golpe.exemplo/x"], r)
        self.assertEqual(codigo, 0)
        self.assertEqual([x["estado"] for x in dados["resultados"]], ["produto", "quebrado"])
        self.assertIn("✓ Abre “Garrafa Térmica Inox 1L”", texto)
        self.assertIn("1 de 2", texto)
        self.assertTrue(dados["quando"])

    def test_sem_link_nao_grava_nada(self):
        codigo, texto, dados = self.rodar(["oi, sem link aqui"], abridor({}))
        self.assertEqual((codigo, dados), (1, None))

    def test_shopee_fora_do_ar_pausa_depois_de_3(self):
        chamadas = []

        def fora(url, timeout):
            chamadas.append(url)
            raise OSError("sem rede")
        links = [f"https://s.shopee.com.br/L{i}" for i in range(6)]
        codigo, _, dados = self.rodar(links, fora)
        self.assertEqual(codigo, 0)
        self.assertEqual(len(chamadas), 3)  # os 3 ultimos nem foram abertos
        self.assertTrue(all(x["estado"] == "sem_resposta" for x in dados["resultados"]))
        self.assertIn("pausada", dados["resultados"][-1]["detalhe"])

    def test_main_despacha_o_comando(self):
        import robo.__main__ as M
        with tempfile.TemporaryDirectory() as tmp:
            antes, M.PASTA_SAIDA = M.PASTA_SAIDA, Path(tmp)
            try:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(M.main(["conferir", "https://golpe.exemplo/x"]), 0)
                self.assertTrue((Path(tmp) / "conferencia.json").exists())
            finally:
                M.PASTA_SAIDA = antes


class TestTelaConferir(unittest.TestCase):
    """A caixa 'Conferir links' do painel e a rota POST /conferir."""

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
        cls.P.SAIDA, cls.P.PORTA = cls.saida_antes, cls.porta_antes
        cls.tmp.cleanup()

    def setUp(self):
        self.chamadas = []
        self.executar_antes = self.P._executar
        self.P._executar = lambda nome, args=None: self.chamadas.append((nome, args))
        self.P._estado.update(rodando=None, aviso_conferir="", codigo=None, ultimo=None)

    def tearDown(self):
        self.P._executar = self.executar_antes
        self.P._estado.update(rodando=None, aviso_conferir="")
        (Path(self.tmp.name) / "conferencia.json").unlink(missing_ok=True)

    def post(self, corpo: str, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        h = {"Origin": f"http://127.0.0.1:{self.porta}", "Content-Type": "application/x-www-form-urlencoded"}
        h.update(headers or {})
        c.request("POST", "/conferir", body=corpo.encode("utf-8"), headers=h)
        r = c.getresponse()
        r.read()
        time.sleep(0.4)  # a linha que chama _executar
        return r.status, r.getheader("Location")

    def test_links_colados_viram_o_comando_sem_shell(self):
        status, destino = self.post("links=" + quote(f"oi {CURTO}\n s.shopee.com.br/XyZ, tchau"))
        self.assertEqual((status, destino), (303, "/#conferir"))
        self.assertEqual(self.chamadas, [("conferir", ["conferir", CURTO, "https://s.shopee.com.br/XyZ"])])

    def test_post_de_outro_site_e_recusado(self):  # CSRF, como nos outros botoes
        status, _ = self.post("links=" + quote(CURTO), {"Origin": "https://site-malicioso.exemplo"})
        self.assertEqual(status, 403)
        self.assertEqual(self.chamadas, [])

    def test_sem_link_ou_grande_demais_so_avisa(self):
        self.post("links=" + quote("nada aqui"))
        self.assertIn("Não achei nenhum link", self.P._estado["aviso_conferir"])
        self.post("links=x", {"Content-Length": str(self.P.LIMITE_CORPO + 1)})
        self.assertIn("grande demais", self.P._estado["aviso_conferir"])
        self.assertEqual(self.chamadas, [])

    def test_com_outra_acao_rodando_nao_dispara(self):
        self.P._estado["rodando"] = "rodar"
        self.post("links=" + quote(CURTO))
        self.assertEqual(self.chamadas, [])
        self.assertIn("outra ação rodando", self.P._estado["aviso_conferir"])

    def test_resultado_na_tela_escapado_e_abrir_so_para_link_da_shopee(self):
        resultados = [
            {"link": CURTO, "estado": "produto", "item": 987654, "loja": 55, "afiliado": "an_1",
             "nome": "<script>alert(1)</script>", "trilha": [], "destino": "shopee.com.br/x", "detalhe": ""},
            {"link": "javascript:alert(2)", "estado": "quebrado", "detalhe": "link fora da Shopee ou endereco invalido",
             "trilha": []},
            {"link": "https://s.shopee.com.br/z", "estado": "INVALIDO"},
            "nem e um dicionario"]
        (Path(self.tmp.name) / "conferencia.json").write_text(
            json.dumps({"quando": "2026-10-20T10:00:00", "resultados": resultados}), encoding="utf-8")
        pagina = self.P._pagina("demo")
        self.assertIn('id="conferir"', pagina)
        self.assertNotIn("<script>alert(1)", pagina)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", pagina)
        self.assertNotIn('href="javascript:', pagina)
        self.assertIn(f'href="{CURTO}"', pagina)
        self.assertNotIn("https://s.shopee.com.br/z", pagina)  # estado invalido nao aparece
        self.assertIn("conferido 20/10 às 10:00", pagina)

    def test_arquivo_estragado_nao_derruba_a_tela(self):
        (Path(self.tmp.name) / "conferencia.json").write_text("{nao e json", encoding="utf-8")
        self.assertIn('id="conferir"', self.P._pagina("demo"))
        (Path(self.tmp.name) / "conferencia.json").write_text('{"quando": "ontem", "resultados": "x"}',
                                                             encoding="utf-8")
        self.assertIn('id="conferir"', self.P._pagina("demo"))


if __name__ == "__main__":
    unittest.main()
