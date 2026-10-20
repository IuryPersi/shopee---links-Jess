"""Painel local: so escuta 127.0.0.1 e so aceita pedidos do proprio painel."""
from __future__ import annotations

import http.client
import re
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import robo.painel as P  # noqa: E402


class TestPainel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), P._Handler)
        cls.porta = cls.srv.server_address[1]
        cls.porta_antes, P.PORTA = P.PORTA, cls.porta  # o handler confere Host/Origin contra a porta real
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        P.PORTA = cls.porta_antes  # 43a rodada: nao deixa a porta do teste para os outros

    def pedir(self, metodo, caminho, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        c.request(metodo, caminho, headers=headers or {})
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace")

    def test_pagina_abre_e_nao_mostra_segredo(self):
        status, corpo = self.pedir("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Achadinhos", corpo)
        # a instrucao mostra o NOME do campo; nunca pode aparecer um VALOR depois do "="
        self.assertIsNone(re.search(r"SHOPEE_SECRET=[^<\s]", corpo))

    def test_host_estranho_e_recusado(self):  # DNS rebinding
        status, _ = self.pedir("GET", "/", {"Host": "site-malicioso.exemplo:%d" % self.porta})
        self.assertEqual(status, 403)

    def test_post_de_outro_site_e_recusado(self):  # CSRF
        status, _ = self.pedir("POST", "/executar/demo", {"Origin": "https://site-malicioso.exemplo"})
        self.assertEqual(status, 403)
        status, _ = self.pedir("POST", "/executar/demo", {})  # sem Origin nem Referer
        self.assertEqual(status, 403)

    def test_referer_com_porta_parecida_e_recusado(self):  # [auditoria] 29a rodada
        status, _ = self.pedir("POST", "/executar/demo", {"Referer": "http://localhost:%d0/" % self.porta})
        self.assertEqual(status, 403)
        status, _ = self.pedir("POST", "/executar/demo", {"Referer": "http://127.0.0.1:%d.mal.exemplo/" % self.porta})
        self.assertEqual(status, 403)

    def test_nao_pode_ser_enquadrado(self):  # [auditoria] 29a rodada - clickjacking
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))

    def test_reserva_e_atomica(self):  # [auditoria] 29a rodada - dois POSTs simultaneos
        P._estado["rodando"] = None
        resultados = []
        barreira = threading.Barrier(8)

        def tenta():
            barreira.wait()
            resultados.append(P.reservar("demo"))
        threads = [threading.Thread(target=tenta) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(resultados.count(True), 1)
        P._estado["rodando"] = None

    def test_comando_desconhecido_nao_roda(self):
        origem = {"Origin": "http://127.0.0.1:%d" % self.porta}
        status, _ = self.pedir("POST", "/executar/rm-rf", origem)
        self.assertEqual(status, 303)
        self.assertIsNone(P._estado["rodando"])


class TestAbrirPainel(unittest.TestCase):
    """PAINEL.bat (`python -m robo.painel --abrir`): navegador so com o painel no ar; segundo clique
    so reabre o navegador; nunca dois paineis na mesma porta (20/10: no Windows o padrao deixava)."""

    def setUp(self):
        self.porta_antes = P.PORTA
        self.abertos = []
        self.abrir_antes = P.webbrowser.open
        P.webbrowser.open = lambda url: self.abertos.append(url)

    def tearDown(self):
        P.PORTA = self.porta_antes
        P.webbrowser.open = self.abrir_antes

    def _no_ar(self, servidor):
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        return servidor.server_address[1]

    def test_dois_paineis_na_mesma_porta_nao_sobem(self):
        primeiro = P._Servidor(("127.0.0.1", 0), P._Handler)
        self.addCleanup(primeiro.server_close)
        with self.assertRaises(OSError):
            P._Servidor(("127.0.0.1", primeiro.server_address[1]), P._Handler)

    def test_segundo_clique_so_abre_o_navegador(self):
        P.PORTA = self._no_ar(P._Servidor(("127.0.0.1", 0), P._Handler))
        saida = __import__("io").StringIO()
        with __import__("contextlib").redirect_stdout(saida):
            self.assertEqual(P.main(["--abrir"]), 0)
        self.assertIn("já está aberto", saida.getvalue())
        self.assertEqual(self.abertos, [f"http://127.0.0.1:{P.PORTA}"])

    def test_porta_de_outro_programa_avisa_e_nao_abre(self):
        from http.server import BaseHTTPRequestHandler

        class Outro(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"outro programa")

            def log_message(self, *_):
                pass
        P.PORTA = self._no_ar(P._Servidor(("127.0.0.1", 0), Outro))
        saida = __import__("io").StringIO()
        with __import__("contextlib").redirect_stdout(saida):
            self.assertEqual(P.main(["--abrir"]), 2)
        self.assertIn("ocupada por outro programa", saida.getvalue())
        self.assertEqual(self.abertos, [])

    def test_navegador_so_abre_com_o_painel_escutando(self):
        import socket
        livre = socket.socket()
        livre.bind(("127.0.0.1", 0))
        P.PORTA = livre.getsockname()[1]
        livre.close()
        escutando = []

        def abrir(url):  # no momento em que o navegador abre, a porta ja aceita conexao?
            with socket.create_connection(("127.0.0.1", P.PORTA), timeout=2):
                escutando.append(url)
        P.webbrowser.open = abrir
        servir_antes = P._Servidor.serve_forever
        P._Servidor.serve_forever = lambda self, *a, **k: None  # nao fica servindo no teste
        try:
            with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
                self.assertEqual(P.main(["--abrir"]), 0)
                self.assertEqual(P.main([]), 0)  # sem --abrir (launch.json/preview): nao abre
        finally:
            P._Servidor.serve_forever = servir_antes
        self.assertEqual(escutando, [f"http://127.0.0.1:{P.PORTA}"])


if __name__ == "__main__":
    unittest.main()
