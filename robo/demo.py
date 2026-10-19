"""Modo demonstracao: produtos FICTICIOS, sem internet e sem credencial.
Serve para ver a vitrine e para os testes. Nenhum nome aqui e de loja/cliente real."""
from __future__ import annotations

import zlib

from .precos import DIA
from .shopee_api import Oferta

# (nome, loja, preco, desconto, vendas, nota, historico de precos em dias atras)
_CATALOGO = {
    "caixa organizadora": [
        ("Kit 6 Caixas Organizadoras Dobráveis com Tampa [Envio Imediato]", "Loja Exemplo Casa", 39.9, 45, 3400, 4.8,
         [(20, 69.9), (12, 68.0), (5, 69.9)]),
        ("Caixa Organizadora Tecido Guarda Roupa 3 Peças", "Loja Exemplo Casa", 24.9, 35, 900, 4.7, []),
    ],
    "jogo de panelas": [
        ("Jogo de Panelas Antiaderente 5 Peças Indução PROMOÇÃO", "Cozinha Fictícia", 189.9, 52, 5200, 4.9,
         [(25, 189.9), (15, 190.0), (6, 189.9)]),
        ("Kit Utensílios de Silicone 12 Peças Cabo de Madeira", "Cozinha Fictícia", 49.9, 40, 12000, 4.8,
         [(28, 79.9), (14, 79.9), (8, 99.9), (2, 79.9)]),
    ],
    "mop giratorio": [
        ("Mop Giratório Balde 360 com 2 Refis Microfibra", "Limpa Tudo Exemplo", 79.9, 38, 8100, 4.8,
         [(22, 119.9), (10, 115.0), (1, 109.9)]),
        ("Mop Spray Reservatório 400ml Limpeza Pesada", "Limpa Tudo Exemplo", 34.9, 31, 300, 4.4, []),
    ],
    "body bebe": [
        ("Kit 5 Bodies Bebê Algodão Manga Curta RN ao 12 meses", "Bebê Modelo", 59.9, 41, 2600, 4.9,
         [(18, 84.9), (9, 82.0), (3, 84.9)]),
        ("Kit Mamadeira Anticólica 3 Peças", "Bebê Modelo", 39.9, 50, 4000, 4.8, []),
    ],
    "almofada amamentacao": [
        ("Almofada de Amamentação Ergonômica Capa Removível", "Mamãe Exemplo", 69.9, 36, 1500, 4.8,
         [(26, 99.9), (11, 99.9), (4, 97.0)]),
    ],
    "organizador geladeira": [
        ("Kit Organizador de Geladeira Acrílico Transparente com Divisórias", "Casa Modelo", 64.9, 47, 6100, 4.9,
         [(24, 109.9), (15, 104.9), (7, 109.9), (2, 108.0)]),
    ],
    "kit cozinha silicone": [
        ("Jogo de Espátulas de Silicone Antiaderente com Suporte de Bambu", "Cozinha Fictícia", 42.9, 44, 9800, 4.9,
         [(26, 74.9), (16, 72.9), (8, 74.9), (3, 74.9)]),
    ],
    "pijama americano": [
        ("Pijama Feminino Americano Cetim Manga Curta com Short", "Moda Fictícia", 59.9, 40, 4300, 4.8,
         [(22, 99.9), (13, 95.0), (6, 99.9), (2, 98.0)]),
    ],
    "enxoval bebe": [
        ("Toalha de Banho Bebê com Capuz Algodão Macio", "Bebê Modelo", 34.9, 42, 7200, 4.9,
         [(25, 59.9), (14, 59.9), (7, 57.9), (1, 59.9)]),
        ("Kit Higiene Bebê Porcelana com Bandeja e Potes", "Bebê Modelo", 79.9, 41, 3100, 4.9,
         [(24, 129.9), (15, 124.9), (8, 129.9), (2, 129.9)]),
    ],
    "bolsa maternidade": [
        ("Bolsa Maternidade Mochila Impermeável com Trocador Portátil", "Mamãe Exemplo", 119.9, 45, 2900, 4.8,
         [(23, 199.9), (12, 189.9), (5, 199.9)]),
    ],
    "pano microfibra": [
        ("Kit Pano de Microfibra Limpeza Multiuso Cozinha e Banheiro", "Limpa Tudo Exemplo", 29.9, 50, 15000, 4.9,
         [(27, 59.9), (18, 57.9), (9, 59.9), (2, 59.9)]),
    ],
    "bolsa feminina": [
        ("Bolsa Feminina Transversal Couro Sintético Alça Corrente", "Moda Fictícia", 54.9, 48, 7300, 4.7,
         [(16, 89.9), (8, 92.0), (2, 89.9)]),
        ("Bolsa Feminina Réplica Primeira Linha", "Moda Fictícia", 99.9, 60, 900, 4.6, []),
    ],
}


# produtos da demo com opcoes de preco diferentes: preco da opcao mais cara = preco x fator
_VARIACOES = {"Pijama Feminino Americano Cetim Manga Curta com Short": 1.6}

# termos de busca da demo por tag (substituem os do nicho.json no modo demo)
BUSCAS_DEMO = {
    "casa": ["caixa organizadora", "organizador geladeira"], "cozinha": ["jogo de panelas", "kit cozinha silicone"],
    "limpeza": ["mop giratorio", "pano microfibra"], "bebe": ["body bebe", "enxoval bebe"],
    "maternidade": ["almofada amamentacao", "bolsa maternidade"], "feminino": ["bolsa feminina", "pijama americano"],
}


class ClienteDemo:
    """Imita o ClienteShopee: mesmas assinaturas, dados inventados."""

    def __init__(self):
        self.chamadas = 0
        self._id = 900000

    def buscar_ofertas(self, keyword=None, sort_type=2, page=1, limit=50, item_id=None, **_):
        self.chamadas += 1
        if item_id is not None:  # reconferencia: devolve o mesmo item, mesmo preco
            for termo in _CATALOGO:
                achou = [o for o in self._itens(termo) if o.item_id == item_id]
                if achou:
                    return achou, False
            return [], False
        if page > 1:
            return [], False
        return self._itens(keyword), False

    def _itens(self, keyword):
        saida = []
        for i, (nome, loja, preco, desc, vendas, nota, _h) in enumerate(_CATALOGO.get(keyword, [])):
            item_id = zlib.crc32(f"{keyword}|{i}".encode()) % 10**9
            saida.append(Oferta(
                item_id=item_id, shop_id=zlib.crc32(loja.encode()) % 10**6, nome=nome, loja=loja,
                preco_min=preco, preco_max=round(preco * _VARIACOES.get(nome, 1.0), 2), desconto=desc,
                vendas=vendas, nota=nota,
                comissao=0.08, imagem="", link_produto=f"https://shopee.com.br/produto-exemplo-i.{item_id}",
                link_oferta=f"https://s.shopee.com.br/exemplo{item_id}",
            ))
        return saida

    def link_curto(self, origin_url, sub_ids=None):
        self.chamadas += 1
        return origin_url.replace("https://shopee.com.br/", "https://s.shopee.com.br/demo-") + "-" + "-".join(sub_ids or [])


def semear_historico(banco, agora: float):
    """Grava o historico ficticio para a demo mostrar todos os vereditos."""
    cli = ClienteDemo()
    for termo, itens in _CATALOGO.items():
        ofertas = cli._itens(termo)
        for o, (*_resto, hist) in zip(ofertas, itens):
            for dias, preco in hist:
                fator = _VARIACOES.get(o.nome, 1.0)
                o2 = Oferta(**{**o.__dict__, "preco_min": preco, "preco_max": round(preco * fator, 2)})
                banco.registrar(o2, ts=agora - dias * DIA)
