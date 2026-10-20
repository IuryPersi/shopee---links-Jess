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
        texto = texto_do_exame(r)
        self.assertIn("A Shopee leva este link ao endereço do produto 987654 (loja 55, nome no endereço: "
                      "“Garrafa Térmica Inox 1L”) e põe a marcação de afiliado an_10000000001.", texto)
        self.assertIn("Toque em Abrir para ver se é o produto certo e se está à venda.", texto)
        self.assertEqual(r["trilha"], [f"301 s.shopee.com.br/AbC123", "200 shopee.com.br/Garrafa-T%C3%A9rmica-Inox-1L-i.55.987654"])
        self.assertNotIn("utm", json.dumps(r["trilha"]))  # a trilha nao leva os parametros

    def test_nenhum_texto_afirma_o_que_nao_foi_medido(self):  # 39a rodada
        proibidas = ("rende comissão", "é o seu", "produto confirmado", "existe", "Abre “")
        casos = [examinar_link(CURTO, abrir=abridor({CURTO: (301, SLUG + MARCA), SLUG + MARCA: (200, None)})),
                 examinar_link(SLUG, abrir=abridor({SLUG: (200, None)})),
                 examinar_link(SLUG + MARCA, abrir=abridor({SLUG + MARCA: (200, None)}))]
        for r in casos:
            texto = texto_do_exame(r)
            for proibida in proibidas:
                self.assertNotIn(proibida, texto.replace("se é o produto certo", ""), texto)

    def test_marcacao_escrita_no_link_colado_nao_ganha_ok(self):  # 39a rodada: o exemplo do Codex
        inventado = "https://shopee.com.br/Produto-Inventado-i.1.1?utm_medium=affiliates&utm_source=an_1"
        r = examinar_link(inventado, abrir=abridor({inventado: (200, None)}))
        self.assertEqual((r["estado"], r["afiliado"], r["marca_escrita"]), ("produto", None, True))
        self.assertEqual(nivel_do_exame(r), "aviso")
        self.assertIn("escrita no próprio link colado: a Shopee não pôs nem confirmou nada", texto_do_exame(r))
        self.assertIn("nome no endereço: “Produto Inventado”", texto_do_exame(r))
        # mesmo que a Shopee redirecione mantendo os parametros escritos a mao
        canonico = "https://shopee.com.br/Produto-Real-i.1.1?utm_medium=affiliates&utm_source=an_1"
        r = examinar_link(inventado, abrir=abridor({inventado: (301, canonico), canonico: (200, None)}))
        self.assertEqual((r["afiliado"], nivel_do_exame(r)), (None, "aviso"))

    def test_marcacao_so_conta_depois_de_um_redirecionamento_da_shopee(self):
        r = examinar_link(SLUG, abrir=abridor({SLUG: (200, None)}))
        self.assertFalse(r["redirecionou"])
        r = examinar_link(CURTO, abrir=abridor({CURTO: (301, SLUG + MARCA), SLUG + MARCA: (200, None)}))
        self.assertTrue(r["redirecionou"])

    def test_link_direto_do_produto_avisa_que_nao_e_de_afiliado(self):
        r = examinar_link(SLUG, abrir=abridor({SLUG: (200, None)}))
        self.assertEqual((r["estado"], r["afiliado"], nivel_do_exame(r)), ("produto", None, "aviso"))
        self.assertIn("a Shopee não pôs a marcação de afiliado no caminho", texto_do_exame(r))
        self.assertIn("ele não é link de afiliado", texto_do_exame(r))

    def test_pagina_que_nao_e_de_produto(self):
        campanha = "https://shopee.com.br/m/vem-ai-dia-de-cupons" + MARCA
        r = examinar_link(CURTO, abrir=abridor({CURTO: (301, campanha), campanha: (200, None)}))
        self.assertEqual((r["estado"], nivel_do_exame(r)), ("outra_pagina", "aviso"))
        self.assertIn("não num endereço de produto", texto_do_exame(r))
        self.assertIn("A Shopee pôs a marcação de afiliado", texto_do_exame(r))
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

    def test_ok_exige_todas_as_provas_explicitas(self):  # 40a rodada: ausencia nunca conta a favor
        base = {"estado": "produto", "item": 1, "loja": 1, "afiliado": "an_1", "redirecionou": True,
                "marca_escrita": False}
        self.assertEqual(nivel_do_exame(base), "ok")
        for falta in ({"redirecionou": None}, {"marca_escrita": None}, {"redirecionou": False},
                      {"marca_escrita": True}, {"afiliado": "sim"}, {"afiliado": "an_1x"}, {"afiliado": 1},
                      {"afiliado": None}):
            r = {**base, **falta}
            for k, v in falta.items():
                if v is None:
                    r.pop(k)
            self.assertEqual(nivel_do_exame(r), "aviso", falta)
            self.assertNotIn("põe a marcação de afiliado an_", texto_do_exame(r), falta)
        sem_campos = {"estado": "produto", "item": 1, "loja": 1, "afiliado": "an_1"}  # registro antigo
        self.assertIn("não deu para confirmar a marcação de afiliado", texto_do_exame(sem_campos))
        sim = {**base, "afiliado": "sim"}
        self.assertIn("sem o ID de afiliado", texto_do_exame(sim))

    def test_frase_de_marcacao_so_com_a_prova_completa(self):  # 41a rodada: em TODO estado
        import itertools
        import re
        from robo.links import _marcacao_da_shopee
        afirma = re.compile(r"(?<!não )(?:pôs|põe) a marcação de afiliado")  # "não pôs" e negacao, vale
        valores = itertools.product(
            ("produto", "outra_pagina", "quebrado", "sem_resposta", None),
            (True, False, None, "sim", 1),          # redirecionou
            (True, False, None, 0, "nao"),          # marca_escrita
            (None, "sim", "an_1", "an_1x", 1, "", "AN_1"))  # afiliado
        for estado, redirecionou, marca_escrita, afiliado in valores:
            r = {"estado": estado, "item": 1, "loja": 1, "destino": "shopee.com.br/x"}
            for chave, valor in (("redirecionou", redirecionou), ("marca_escrita", marca_escrita),
                                 ("afiliado", afiliado)):
                if valor is not None:
                    r[chave] = valor
            texto = texto_do_exame(r)
            if _marcacao_da_shopee(r) is None:
                self.assertIsNone(afirma.search(texto), (r, texto))
                self.assertNotEqual(nivel_do_exame(r), "ok", r)
            elif estado == "produto":
                self.assertIsNotNone(afirma.search(texto), (r, texto))  # o caso bom continua dizendo
                self.assertEqual(nivel_do_exame(r), "ok", r)

    def test_pagina_que_nao_e_de_produto_so_com_utm_medium(self):  # o caminho exato da 41a
        campanha = "https://shopee.com.br/m/campanha?utm_medium=affiliates"
        r = examinar_link(CURTO, abrir=abridor({CURTO: (302, campanha), campanha: (200, None)}))
        self.assertEqual((r["estado"], r["redirecionou"], r["marca_escrita"], r["afiliado"]),
                         ("outra_pagina", True, False, "sim"))
        self.assertNotIn("pôs a marcação", texto_do_exame(r))
        self.assertIn("sem o ID de afiliado", texto_do_exame(r))

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
        self.assertIn("✓ A Shopee leva este link ao endereço do produto 987654", texto)
        self.assertIn("em 1 de 2", texto)
        self.assertTrue(dados["quando"])
        from robo.links import VERSAO_CONFERENCIA
        self.assertEqual(dados["versao"], VERSAO_CONFERENCIA)  # a tela so mostra a versao atual

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
        # sem '#': com '#conferir' a recarga automatica nao recarregava (teste da tela, 20/10)
        self.assertEqual((status, destino), (303, "/?aba=conferir"))
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
            json.dumps({"versao": self.P.VERSAO_CONFERENCIA, "quando": "2026-10-20T10:00:00",
                        "resultados": resultados}), encoding="utf-8")
        pagina = self.P._pagina("demo")
        self.assertIn('id="conferir"', pagina)
        self.assertNotIn("<script>alert(1)", pagina)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", pagina)
        self.assertNotIn('href="javascript:', pagina)
        self.assertIn(f'href="{CURTO}"', pagina)
        self.assertNotIn("https://s.shopee.com.br/z", pagina)  # estado invalido nao aparece
        self.assertIn("conferido 20/10 às 10:00", pagina)

    def test_resultado_de_versao_anterior_nao_aparece_na_tela(self):  # 40a rodada: o caminho do Codex
        inventado = "https://shopee.com.br/Produto-Inventado-i.1.1?utm_medium=affiliates&utm_source=an_1"
        antigo = {"quando": "2026-10-20T09:00:00", "resultados": [  # gravado pela versao de 0ef2304
            {"link": inventado, "estado": "produto", "item": 1, "loja": 1, "nome": "Produto Inventado",
             "afiliado": "an_1", "trilha": ["200 shopee.com.br/Produto-Inventado-i.1.1"], "detalhe": ""}]}
        (Path(self.tmp.name) / "conferencia.json").write_text(json.dumps(antigo), encoding="utf-8")
        pagina = self.P._pagina("demo")
        self.assertNotIn('<span class="ic">✓</span>', pagina)
        self.assertNotIn("põe a marcação de afiliado an_1", pagina)
        self.assertIn("versão anterior do robô", pagina)
        self.assertIn("Produto-Inventado-i.1.1?utm_medium=affiliates&amp;utm_source=an_1</textarea>", pagina)

    def test_conexao_que_nao_manda_o_corpo_nao_prende_para_sempre(self):  # 39a rodada (risco)
        self.assertTrue(0 < self.P._Handler.timeout <= 30)

    def test_envio_lento_tem_prazo_total(self):  # 40a rodada (risco)
        import socket
        antes, self.P.PRAZO_CORPO = self.P.PRAZO_CORPO, 0.4
        try:
            s = socket.create_connection(("127.0.0.1", self.porta), timeout=5)
            s.sendall((f"POST /conferir HTTP/1.1\r\nHost: 127.0.0.1:{self.porta}\r\n"
                       f"Origin: http://127.0.0.1:{self.porta}\r\nContent-Type: application/x-www-form-urlencoded\r\n"
                       f"Content-Length: 1000\r\n\r\nlinks=https").encode())
            inicio = time.monotonic()
            resposta = s.recv(200)  # o resto do corpo nunca chega
            s.close()
        finally:
            self.P.PRAZO_CORPO = antes
        self.assertLess(time.monotonic() - inicio, 3)
        self.assertIn(b"303", resposta)
        self.assertIn("chegou incompleto", self.P._estado["aviso_conferir"])
        self.assertEqual(self.chamadas, [])

    def test_envio_pingado_tambem_para_no_prazo_total(self):  # 41a rodada (risco): 1 byte a cada 0,1 s
        import socket
        antes, self.P.PRAZO_CORPO = self.P.PRAZO_CORPO, 0.5
        parar = threading.Event()
        s = socket.create_connection(("127.0.0.1", self.porta), timeout=5)
        try:
            s.sendall((f"POST /conferir HTTP/1.1\r\nHost: 127.0.0.1:{self.porta}\r\n"
                       f"Origin: http://127.0.0.1:{self.porta}\r\nContent-Type: application/x-www-form-urlencoded\r\n"
                       f"Content-Length: 1000\r\n\r\nlinks=").encode())

            def pingar():  # nunca fica 0,5 s parado: so o prazo TOTAL corta
                while not parar.is_set():
                    try:
                        s.sendall(b"a")
                    except OSError:
                        return
                    time.sleep(0.1)
            threading.Thread(target=pingar, daemon=True).start()
            inicio = time.monotonic()
            resposta = s.recv(200)
            decorrido = time.monotonic() - inicio
        finally:
            parar.set()
            self.P.PRAZO_CORPO = antes
            s.close()
        self.assertLess(decorrido, 2.5)  # sem o prazo total, 1000 bytes pingados levariam ~100 s
        self.assertIn(b"303", resposta)
        self.assertIn("chegou incompleto", self.P._estado["aviso_conferir"])
        self.assertEqual(self.chamadas, [])

    def test_pagina_abre_a_caixa_quando_volta_da_conferencia(self):
        self.assertIn("get('aba')==='conferir'", self.P.JS)
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        c.request("GET", "/?aba=conferir")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn('id="conferir"', r.read().decode("utf-8"))

    def test_arquivo_estragado_nao_derruba_a_tela(self):
        (Path(self.tmp.name) / "conferencia.json").write_text("{nao e json", encoding="utf-8")
        self.assertIn('id="conferir"', self.P._pagina("demo"))
        (Path(self.tmp.name) / "conferencia.json").write_text('{"quando": "ontem", "resultados": "x"}',
                                                             encoding="utf-8")
        self.assertIn('id="conferir"', self.P._pagina("demo"))


if __name__ == "__main__":
    unittest.main()
