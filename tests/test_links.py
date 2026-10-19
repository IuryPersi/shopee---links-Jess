"""Conferencia dos links: tudo com respostas FALSAS (sem internet)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from robo.links import conferir_link, host_shopee  # noqa: E402


def abridor(respostas: dict):
    """respostas: url -> (status, location). URL nao listada levanta erro de rede."""
    def abrir(url, timeout):
        if url not in respostas:
            raise OSError("sem rede")
        return respostas[url]
    return abrir


class TestConferirLink(unittest.TestCase):
    def test_link_curto_que_leva_ao_produto(self):
        r = abridor({
            "https://s.shopee.com.br/AbC123": (302, "https://shopee.com.br/universal-link?redir=1"),
            "https://shopee.com.br/universal-link?redir=1": (302, "/produto-exemplo-i.55.987654"),
            "https://shopee.com.br/produto-exemplo-i.55.987654": (200, None),
        })
        estado, destino = conferir_link("https://s.shopee.com.br/AbC123", 987654, abrir=r)
        self.assertEqual(estado, "ok")
        self.assertIn("987654", destino)

    # ---- 33a rodada do Codex ----
    def test_id_exato_nao_trecho_de_outro_numero(self):
        for destino in ("https://shopee.com.br/product/987654/111",      # 987654 e a LOJA
                        "https://shopee.com.br/produto-i.55.19876540"):  # ID maior que contem o numero
            r = abridor({"https://s.shopee.com.br/x": (302, destino), destino: (200, None)})
            estado, detalhe = conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)
            self.assertEqual(estado, "quebrado", destino)  # e a pagina de OUTRO produto
            self.assertIn("OUTRO produto", detalhe)

    def test_selo_so_se_o_destino_abrir(self):
        r = abridor({"https://s.shopee.com.br/x": (302, "/product/55/987654"),
                     "https://s.shopee.com.br/product/55/987654": (404, None)})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], "quebrado")
        r2 = abridor({"https://s.shopee.com.br/x": (302, "https://shopee.com.br/product/55/987654"),
                      "https://shopee.com.br/product/55/987654": (302, "https://shope.ee/error_page")})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r2)[0], "quebrado")
        r3 = abridor({"https://s.shopee.com.br/x": (302, "https://shopee.com.br/product/55/987654"),
                      "https://shopee.com.br/product/55/987654": (403, None)})  # anti-robo: sem selo
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r3)[0], "sem_resposta")

    def test_endereco_malformado_nao_derruba(self):
        r = abridor({"https://s.shopee.com.br/x": (302, "https://[shopee.com.br/x")})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 1, abrir=r)[0], "quebrado")
        self.assertEqual(conferir_link("https://[shopee.com.br/x", 1, abrir=abridor({}))[0], "quebrado")

    def test_produto_com_error_no_nome_nao_e_pagina_de_erro(self):
        destino = "https://shopee.com.br/Terror-Livro-i.55.987654"
        r = abridor({"https://s.shopee.com.br/x": (302, destino), destino: (200, None)})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], "ok")

    def test_redirecionamento_sem_https_porta_ou_usuario_e_quebrado(self):
        for destino in ("http://shopee.com.br/product/55/987654", "https://shopee.com.br:8080/product/55/987654",
                        "https://usuario@shopee.com.br/product/55/987654", "ftp://shopee.com.br/x",
                        "https://shopee.com.br@golpe.exemplo/x"):
            r = abridor({"https://s.shopee.com.br/x": (302, destino)})
            self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], "quebrado", destino)

    def test_item_da_pagina(self):
        from robo.links import item_da_pagina
        self.assertEqual(item_da_pagina("https://shopee.com.br/product/55/987654"), 987654)
        self.assertEqual(item_da_pagina("https://shopee.com.br/product/55/987654/"), 987654)
        self.assertEqual(item_da_pagina("https://shopee.com.br/universal-link/product/55/987654?x=1"), 987654)
        self.assertEqual(item_da_pagina("https://shopee.com.br/Kit-Potes-i.55.987654?sp=1"), 987654)
        # 34a rodada: parametro na consulta nao prova pagina de produto
        self.assertIsNone(item_da_pagina("https://shopee.com.br/universal-link?itemid=987654&shopid=55"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/buyer/login?itemid=987654"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/buyer/login/product/55/987654"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/product/55/987654/avaliacoes"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/m/oferta"))
        self.assertIsNone(item_da_pagina("https://[quebrado"))
        # so digitos ASCII, sem zero a esquerda e com tamanho de ID de verdade
        for estranho in ("²", "٩٨٧٦٥٤", "0987654", "9" * 4301, "%C2%B2"):
            self.assertIsNone(item_da_pagina(f"https://shopee.com.br/product/55/{estranho}"), estranho[:12])
            self.assertIsNone(item_da_pagina(f"https://shopee.com.br/Kit-i.55.{estranho}"), estranho[:12])

    # ---- 34a rodada do Codex ----
    def test_vale_a_pagina_final_nao_um_endereco_do_meio(self):
        meio = "https://shopee.com.br/product/55/987654"
        for final, esperado in (("https://shopee.com.br/product/55/111", "quebrado"),  # outro produto
                                ("https://shopee.com.br/buyer/login", "ok_sem_id")):   # login: sem selo
            r = abridor({"https://s.shopee.com.br/x": (302, meio), meio: (302, final), final: (200, None)})
            self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], esperado, final)

    def test_itemid_em_pagina_qualquer_nao_ganha_selo(self):
        final = "https://shopee.com.br/buyer/login?itemid=987654"
        r = abridor({"https://s.shopee.com.br/x": (302, final), final: (200, None)})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], "ok_sem_id")

    def test_id_estranho_nao_derruba_a_rodada(self):
        for estranho in ("%C2%B2", "²", "9" * 4301):
            for final in (f"https://shopee.com.br/x?itemid={estranho}", f"https://shopee.com.br/product/55/{estranho}"):
                def r(url, timeout, final=final):
                    return (302, final) if url == "https://s.shopee.com.br/x" else (200, None)
                self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], "ok_sem_id",
                                 final[:60])
        # ID esperado estranho tambem nunca ganha o selo nem derruba
        destino = "https://shopee.com.br/product/55/987654"
        r = abridor({"https://s.shopee.com.br/x": (302, destino), destino: (200, None)})
        for item in (None, True, "²", "9" * 4301, -5, 0, 3.5, object()):
            self.assertEqual(conferir_link("https://s.shopee.com.br/x", item, abrir=r)[0], "ok_sem_id", repr(item))
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", "987654", abrir=r)[0], "ok")

    def test_nunca_levanta_excecao(self):
        def abrir_defeituoso(url, timeout):
            return None  # nao e (status, location): defeito, nao rede
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 1, abrir=abrir_defeituoso)[0], "sem_resposta")
        estado, detalhe = conferir_link("https://s.shopee.com.br/x", 1, abrir=lambda u, t: ("abc", None))
        self.assertEqual((estado, detalhe), ("sem_resposta", "falha ao conferir: TypeError"))

    def test_prazo_total_por_link(self):
        agora = [0.0]

        def relogio():
            return agora[0]

        def abrir_lento(url, timeout):
            agora[0] += 11  # cada salto leva 11 s
            return 302, "https://shopee.com.br/product/55/987654"
        estado, detalhe = conferir_link("https://s.shopee.com.br/x", 987654, abrir=abrir_lento,
                                        prazo_total=30, relogio=relogio)
        self.assertEqual(estado, "sem_resposta")
        self.assertIn("30s", detalhe)
        self.assertLessEqual(agora[0], 33)  # parou no prazo, nao seguiu os 8 saltos

    def test_timeout_de_cada_salto_respeita_o_que_sobra_do_prazo(self):
        pedidos = []
        agora = [0.0]

        def abrir(url, timeout):
            pedidos.append(timeout)
            agora[0] += 25
            return 302, "https://shopee.com.br/product/55/987654"
        conferir_link("https://s.shopee.com.br/x", 987654, abrir=abrir, prazo_total=30, timeout=10,
                      relogio=lambda: agora[0])
        self.assertEqual(pedidos, [10, 5])

    def test_location_com_barra_invertida_ou_espaco_e_quebrado(self):
        for destino in ("https:\\\\golpe.exemplo/x", "/\\golpe.exemplo", "https://shopee.com.br/a b", "/x\r\nSet-Cookie: a"):
            r = abridor({"https://s.shopee.com.br/x": (302, destino)})
            self.assertEqual(conferir_link("https://s.shopee.com.br/x", 1, abrir=r)[0], "quebrado", repr(destino))

    def test_nome_com_acento_no_redirecionamento_e_seguido(self):
        # o http.client entrega o cabecalho decodificado em latin-1: 'é' em UTF-8 chega como 'Ã©'
        bruto = "https://shopee.com.br/Garrafa-Térmica-i.55.987654".encode("utf-8").decode("latin-1")
        final = "https://shopee.com.br/Garrafa-T%C3%A9rmica-i.55.987654"
        r = abridor({"https://s.shopee.com.br/x": (302, bruto), final: (200, None)})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], "ok")

    # ---- 35a rodada do Codex ----
    def test_link_inicial_com_barra_invertida_nao_ganha_selo(self):
        chamadas = []

        def abrir(url, timeout):
            chamadas.append(url)
            return 200, None
        for url in ("https://shopee.com.br/buyer\\login-i.55.987654", "https://s.shopee.com.br/a b",
                    "https://s.shopee.com.br/x\ty", "https://s.shopee.com.br/Térmica"):
            self.assertEqual(conferir_link(url, 987654, abrir=abrir)[0], "quebrado", repr(url))
        self.assertEqual(chamadas, [])  # nem chegou a abrir

    def test_nome_do_produto_no_caminho(self):
        from robo.links import item_da_pagina
        self.assertIsNone(item_da_pagina("https://shopee.com.br/buyer\\login-i.55.987654"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/buyer%2Flogin-i.55.987654"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/buyer%5clogin-i.55.987654"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/a%00b-i.55.987654"))
        self.assertIsNone(item_da_pagina("https://shopee.com.br/-i.55.987654"))  # sem nome
        self.assertEqual(item_da_pagina("https://shopee.com.br/Lampada-%C3%A0-Pilha-i.55.987654"), 987654)
        self.assertEqual(item_da_pagina("https://shopee.com.br/Kit-(3)-Potes_500ml-i.55.987654"), 987654)

    def test_acento_cujo_utf8_tem_byte_a0_e_seguido(self):
        # 'à' em UTF-8 = C3 A0; lido em latin-1, o A0 parece espaco (35a rodada)
        bruto = "https://shopee.com.br/Lampada-à-Pilha-i.55.987654".encode("utf-8").decode("latin-1")
        self.assertIn("\xa0", bruto)
        final = "https://shopee.com.br/Lampada-%C3%A0-Pilha-i.55.987654"
        r = abridor({"https://s.shopee.com.br/x": (302, bruto), final: (200, None)})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 987654, abrir=r)[0], "ok")

    def test_regex_do_nome_nao_trava_com_endereco_hostil(self):
        import time
        from robo.links import item_da_pagina
        inicio = time.monotonic()
        for caminho in ("/" + "-i.1" * 20000 + "x", "/" + "a" * 50000 + "-i.55.", "/" + "%C3" * 20000 + "-i.5.x"):
            self.assertIsNone(item_da_pagina("https://shopee.com.br" + caminho))
        self.assertLess(time.monotonic() - inicio, 2)

    # ---- 36a rodada do Codex ----
    def test_so_formas_que_python_e_navegador_leem_igual(self):
        bom = "https://shopee.com.br/product/55/987654"
        for location in ("///product/55/987654",            # navegador: host 'product'
                         "////product/55/987654", "//product/55/987654", "https:product/55/987654",
                         "https:///product/55/987654", "product/55/987654", "?itemid=987654", "#x",
                         "/x/../product/55/987654", "/./product/55/987654", "/x/%2e%2E/product/55/987654",
                         "/x/.%2e/product/55/987654", "https://shopee.com.br/x/../product/55/987654",
                         "https://shopee.com.br%2F@golpe.exemplo/", "https://shopee.com.br:443@golpe.exemplo/",
                         "https://shopee.com.br./product/55/987654", "https://-shopee.com.br/x"):
            def r(url, timeout, location=location):
                return (302, location) if url == "https://shopee.com.br/x" else (200, None)
            estado, _ = conferir_link("https://shopee.com.br/x", 987654, abrir=r)
            self.assertEqual(estado, "quebrado", location)
        # as formas boas continuam valendo (absoluta, com :443, maiusculas, caminho com 1 barra)
        for location, final in ((bom, bom), ("https://shopee.com.br:443/product/55/987654",
                                             "https://shopee.com.br:443/product/55/987654"),
                                ("HTTPS://SHOPEE.COM.BR/product/55/987654", "HTTPS://SHOPEE.COM.BR/product/55/987654"),
                                ("/product/55/987654", bom)):
            r = abridor({"https://shopee.com.br/x": (302, location), final: (200, None)})
            self.assertEqual(conferir_link("https://shopee.com.br/x", 987654, abrir=r)[0], "ok", location)

    def test_link_inicial_tambem_so_na_forma_limpa(self):
        chamadas = []

        def abrir(url, timeout):
            chamadas.append(url)
            return 200, None
        for url in ("https:///s.shopee.com.br/x", "https:s.shopee.com.br/x", "https://s.shopee.com.br/a/../x",
                    "https://s.shopee.com.br:443@golpe.exemplo/x", "https://s.shopee.com.br./x"):
            self.assertEqual(conferir_link(url, 1, abrir=abrir)[0], "quebrado", url)
        self.assertEqual(chamadas, [])

    def test_trilha_sem_parametros_de_rastreio(self):
        final = "https://shopee.com.br/product/55/987654?utm_source=an_123&utm_content=abc"
        r = abridor({"https://s.shopee.com.br/x": (302, final), final: (200, None)})
        trilha = []
        estado, detalhe = conferir_link("https://s.shopee.com.br/x", 987654, abrir=r, trilha=trilha)
        self.assertEqual(estado, "ok")
        self.assertEqual(trilha, ["302 s.shopee.com.br/x", "200 shopee.com.br/product/55/987654"])
        self.assertNotIn("utm", detalhe)

    def test_produto_removido_e_quebrado(self):
        r = abridor({"https://s.shopee.com.br/x": (404, None)})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 1, abrir=r)[0], "quebrado")

    def test_redirecionar_para_fora_da_shopee_e_quebrado(self):
        r = abridor({"https://s.shopee.com.br/x": (302, "https://site-estranho.exemplo/pagina")})
        estado, detalhe = conferir_link("https://s.shopee.com.br/x", 1, abrir=r)
        self.assertEqual(estado, "quebrado")
        self.assertIn("fora da Shopee", detalhe)

    def test_link_que_nao_e_da_shopee_nem_e_aberto(self):
        chamadas = []
        estado, _ = conferir_link("https://encurtador.exemplo/abc", 1, abrir=lambda u, t: chamadas.append(u))
        self.assertEqual(estado, "quebrado")
        self.assertEqual(chamadas, [])
        self.assertEqual(conferir_link("http://s.shopee.com.br/x", 1, abrir=abridor({}))[0], "quebrado")

    def test_shopee_sem_responder_nao_derruba_e_nao_confirma(self):
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 1, abrir=abridor({}))[0], "sem_resposta")
        r = abridor({"https://s.shopee.com.br/x": (403, None)})  # bloqueio anti-robo
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 1, abrir=r)[0], "sem_resposta")

    def test_link_inexistente_cai_na_pagina_de_erro_e_e_quebrado(self):
        # comportamento REAL observado em 19/10/2026: 301 para shope.ee/error_page, que responde 200
        r = abridor({"https://s.shopee.com.br/codigoInexistente": (301, "https://shope.ee/error_page"),
                     "https://shope.ee/error_page": (200, None)})
        estado, detalhe = conferir_link("https://s.shopee.com.br/codigoInexistente", 123456, abrir=r)
        self.assertEqual(estado, "quebrado")
        self.assertIn("erro", detalhe)

    def test_abriu_na_shopee_sem_mostrar_o_id(self):
        r = abridor({"https://s.shopee.com.br/x": (302, "https://shopee.com.br/m/oferta"),
                     "https://shopee.com.br/m/oferta": (200, None)})
        self.assertEqual(conferir_link("https://s.shopee.com.br/x", 77, abrir=r)[0], "ok_sem_id")

    def test_hosts(self):
        self.assertTrue(host_shopee("https://s.shopee.com.br/a"))
        self.assertTrue(host_shopee("https://shopee.com.br/a"))
        self.assertTrue(host_shopee("https://shope.ee/a"))
        self.assertFalse(host_shopee("https://shopee.com.br.golpe.exemplo/a"))
        self.assertFalse(host_shopee("https://falsoshopee.com.br/a"))


class TestRodadaConfereLinks(unittest.TestCase):
    def test_link_quebrado_nao_vai_para_a_tela(self):
        from tests.test_robo import CFG, AGORA, FakeClienteRodada, oferta, quieto
        from robo.banco import Banco
        from robo.pipeline import rodar
        ofs = [oferta(item_id=1, shop_id=1, nome="Garrafa Térmica Inox 1L"),
               oferta(item_id=2, shop_id=2, nome="Tábua de Corte Bambu"),
               oferta(item_id=3, shop_id=3, nome="Escorredor de Louça Aço")]
        estados = {1: ("ok", "x"), 2: ("quebrado", "HTTP 404"), 3: ("sem_resposta", "HTTP 403")}

        def verificador(link, item_id):
            return estados[item_id]
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada(ofs), Banco(":memory:"), CFG, Path(tmp), agora=AGORA,
                        log=quieto, verificador=verificador)
        por_id = {c.oferta.item_id: c for c in res.escolhidos["cozinha"]}
        self.assertNotIn(2, por_id)  # quebrado: fora
        self.assertTrue(por_id[1].link_conferido)
        self.assertFalse(por_id[3].link_conferido)  # sem resposta: fica, sem o selo
        self.assertEqual(res.recusados["link não abre o produto na Shopee"], 1)
        self.assertEqual(res.links_sem_conferencia, 1)  # vira aviso no fim da rodada

    def test_defeito_no_verificador_nao_derruba_a_rodada(self):
        from tests.test_robo import CFG, AGORA, FakeClienteRodada, oferta, quieto
        from robo.banco import Banco
        from robo.pipeline import rodar
        ofs = [oferta(item_id=1, shop_id=1, nome="Garrafa Térmica Inox 1L"),
               oferta(item_id=2, shop_id=2, nome="Tábua de Corte Bambu")]

        def verificador(link, item_id):
            if item_id == 2:
                raise ValueError("defeito")
            return "ok", "x"
        with tempfile.TemporaryDirectory() as tmp:
            res = rodar(FakeClienteRodada(ofs), Banco(":memory:"), CFG, Path(tmp), agora=AGORA,
                        log=quieto, verificador=verificador)
        por_id = {c.oferta.item_id: c for c in res.escolhidos["cozinha"]}
        self.assertTrue(por_id[1].link_conferido)
        self.assertFalse(por_id[2].link_conferido)  # ficou na tela, sem o selo


class TestVerificadorComPrazo(unittest.TestCase):
    def test_link_que_trava_nao_segura_a_rodada(self):
        import threading
        import time
        from robo.links import verificador_com_pausa
        liberar = threading.Event()

        def abrir_travado(url, timeout):
            liberar.wait(10)  # simula conexao que nao termina
            return 200, None
        verificar = verificador_com_pausa(pausa=0, prazo_total=0.2, folga=0.1, abrir=abrir_travado)
        inicio = time.monotonic()
        try:
            estado, detalhe = verificar("https://s.shopee.com.br/x", 1)
        finally:
            liberar.set()
        self.assertEqual(estado, "sem_resposta")
        self.assertLess(time.monotonic() - inicio, 2)

    def test_verificador_normal_devolve_o_resultado(self):
        from robo.links import verificador_com_pausa
        destino = "https://shopee.com.br/product/55/987654"
        r = abridor({"https://s.shopee.com.br/x": (302, destino), destino: (200, None)})
        verificar = verificador_com_pausa(pausa=0, abrir=r)
        self.assertEqual(verificar("https://s.shopee.com.br/x", 987654)[0], "ok")

    def test_prazo_duro_tambem_no_diagnostico(self):
        import threading
        import time
        from robo.links import conferir_com_prazo
        liberar = threading.Event()

        def abrir_travado(url, timeout):
            liberar.wait(10)
            return 200, None
        trilha = []
        inicio = time.monotonic()
        try:
            estado, _ = conferir_com_prazo("https://s.shopee.com.br/x", 1, prazo_total=0.2, folga=0.1,
                                           abrir=abrir_travado, trilha=trilha)
        finally:
            liberar.set()
        self.assertEqual(estado, "sem_resposta")
        self.assertLess(time.monotonic() - inicio, 2)
        destino = "https://shopee.com.br/product/55/987654"
        r = abridor({"https://s.shopee.com.br/x": (302, destino), destino: (200, None)})
        trilha = []
        self.assertEqual(conferir_com_prazo("https://s.shopee.com.br/x", 987654, abrir=r, trilha=trilha)[0], "ok")
        self.assertEqual(trilha, ["302 s.shopee.com.br/x", "200 shopee.com.br/product/55/987654"])

    def test_shopee_parou_de_responder_a_conferencia_pausa(self):
        from robo.links import verificador_com_pausa
        abertos = []
        respostas = {"https://s.shopee.com.br/ok": (302, "https://shopee.com.br/product/55/987654"),
                     "https://shopee.com.br/product/55/987654": (200, None)}

        def abrir(url, timeout):
            abertos.append(url)
            if url in respostas:
                return respostas[url]
            return 429, None  # limite de pedidos
        verificar = verificador_com_pausa(pausa=0, abrir=abrir, desistir_apos=3)
        self.assertEqual(verificar("https://s.shopee.com.br/a", 1)[0], "sem_resposta")
        self.assertEqual(verificar("https://s.shopee.com.br/ok", 987654)[0], "ok")  # zera a contagem
        for letra in "bcd":
            self.assertEqual(verificar(f"https://s.shopee.com.br/{letra}", 1)[0], "sem_resposta")
        antes = len(abertos)
        estado, detalhe = verificar("https://s.shopee.com.br/e", 1)
        self.assertEqual((estado, len(abertos)), ("sem_resposta", antes))  # nem tentou abrir
        self.assertIn("pausada", detalhe)


class TestMotivoNaTela(unittest.TestCase):
    def test_erro_de_acesso_aparece_em_portugues(self):
        import robo.painel as P
        saida = ("Coletando ofertas na Shopee...\nPAROU (conta/credencial): [10035] You currently do not have "
                 "access -> a conta ainda nao tem acesso a Open API. Pedir a liberacao (gratis) no formulario "
                 "https://help.shopee.com.br/portal/webform/x e aguardar o e-mail")
        motivo = P._motivo(saida)
        self.assertTrue(motivo.startswith("a conta ainda nao tem acesso a Open API"), motivo)
        self.assertEqual(P._motivo("Faltam credenciais no arquivo .env: SHOPEE_APP_ID"),
                         "Faltam credenciais no arquivo .env: SHOPEE_APP_ID")


if __name__ == "__main__":
    unittest.main()
