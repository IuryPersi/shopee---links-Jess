"""Vocabulario PERMITIDO no nome do produto que vai para a legenda (27a rodada do Codex).

Depois de 27 rodadas ficou provado que nenhuma lista de PROIBIDOS fecha texto livre
(numerais romanos, gratuidade em linguagem natural, girias...). Entao o nome publicado so
pode conter palavras DESTA lista - produtos, materiais, cores e caracteristicas do nicho -
mais as palavras das tags do config (que passam pelos mesmos filtros). Palavra fora daqui
nao sai na legenda. Por construcao: nao ha numero, moeda, giria, promessa de gratis,
comparativo de preco nem nome de marca desconhecido.

Regras para quem for AUMENTAR a lista: so substantivo/adjetivo descritivo de produto.
Nunca numero, quantidade, moeda, comparativo (menor, melhor, maior, mais), preco, custo,
valor, gratis, promocao, oferta, nem palavra que sozinha prometa algo.
Formas sem acento e em minusculas (a comparacao normaliza).
"""

CONECTORES = {"de", "da", "do", "das", "dos", "com", "para", "e", "em", "sem", "tipo"}

PALAVRAS = set("""
kit conjunto jogo colecao linha
caixa caixinha pote potinho organizador organizadora organizadores organizadoras nicho nichos cesto cesta
prateleira suporte gancho cabide cabideiro sapateira gaveteiro divisoria divisor colmeia bandeja porta
tampa tampas alca alcas cabo base capa fronha lencol edredom cobertor manta mantinha colcha travesseiro
almofada almofadas tapete tapetes passadeira cortina cortinas persiana varao luminaria abajur lampada
espelho quadro relogio vaso vasinho planta flor flores decoracao decorativo decorativa enfeite
toalha toalhas roupao rosto banho praia mesa cadeira banco banqueta puff sofa poltrona rack estante
guarda roupa roupeiro arara closet cama casal solteiro queen king berco
cozinha panela panelas frigideira caçarola cacarola wok chaleira bule cafeteira jarra garrafa
garrafinha squeeze copo copos caneca canecas xicara xicaras taca tacas prato pratos travessa tigela
bowl pote potes marmita marmitas lancheira hermetico hermeticos hermetica hermeticas utensilio utensilios
espatula concha colher colheres garfo garfos faca facas talher talheres pegador escumadeira peneira
escorredor ralador fatiador mandoline descascador abridor saca rolha tabua tabuas assadeira assadeiras
forma formas forminha forminhas fôrma liquidificador mixer batedeira processador espremedor sanduicheira
grill fritadeira airfryer air fryer panificadora torradeira micro ondas cooktop fogao forno queimador
queimadores porta tempero temperos condimentos dispenser saleiro acucareiro manteigueira fruteira
lixeira lixeiras galheteiro rodinho pano panos guardanapo jogo americano descanso
limpeza mop rodo vassoura esfregao esponja esponjas escova escovas balde baldes flanela microfibra
desentupidor aspirador pa coletor dispensador borrifador pulverizador refil refis luva luvas
lavanderia varal prendedor prendedores cesto roupa roupas tanque
bebe bebes infantil recem nascido rn body bodies bodys macacao macacoes mijao mijoes conjuntinho
babador babadores mordedor mordedores chocalho trocador fralda fraldas lenco umedecido banheira
banheirinha toalhinha capuz enxoval saida maternidade mosquiteiro bolsa bolsas mochila frasqueira
amamentacao amamentar gestante gravida gestacao pos parto almofada cinta sutia sutias camisola
absorvente seio seios concha protetor kit higiene sapatinho meias touca luvinha manta
feminina feminino mulher vestido vestidos saia saias blusa blusas cropped camiseta camisetas regata
regatas conjunto short shorts calca calcas legging leggings macaquinho macacao jaqueta casaco cardigan
pijama pijamas camisola lingerie calcinha calcinhas sutia biquini maio saida praia sandalia
sandalias rasteirinha rasteira tamanco salto tenis chinelo chinelos bota botas sapatilha bolsa bolsas
carteira necessaire brinco brincos colar colares pulseira pulseiras anel aneis tornozeleira corrente
pingente relogio oculos tiara presilha presilhas piranha xuxinha elastico laco lacos faixa
maquiagem batom base corretivo rimel mascara sombra paleta pincel pinceis esponja delineador gloss
skincare serum hidratante creme protetor sabonete demaquilante tonico esfoliante mascara facial
cabelo capilar chapinha prancha secador escova secadora babyliss modelador pente
algodao linho seda cetim viscose malha moletom trico renda jeans couro sintetico tecido veludo
plush pelucia la poliester nylon silicone bambu madeira vidro plastico acrilico inox aco aluminio
ceramica porcelana ferro fundido metal metalico mdf palha vime rattan pedra marmore granito borracha
eva espuma latex resina papelao lona feltro juta
branco branca brancos brancas preto preta pretos pretas cinza rosa rosê pink azul azuis verde verdes
amarelo amarela vermelho vermelha laranja roxo roxa lilas bege marrom nude caramelo dourado dourada
prateado prateada transparente colorido colorida coloridos coloridas estampado estampada liso lisa
listrado listrada xadrez floral natural fosco fosca brilhante
dobravel dobraveis retratil portatil portateis eletrico eletrica eletricos termico termica termicos
antiaderente antiderrapante giratorio giratoria magnetico magnetica adesivo adesiva impermeavel
lavavel reforcado reforcada resistente compacto compacta grande grandes pequeno pequena pequenos
pequenas medio media mini minis infantil adulto unissex ajustavel regulavel empilhavel modular
multiuso multifuncional automatico automatica recarregavel sem fio bluetooth usb led luz
redondo redonda quadrado quadrada retangular oval alto alta longo longa curto curta
manga regata gola alcinha acolchoado acolchoada macio macia confortavel elegante moderno moderna
classico classica minimalista rustico rustica vintage nordico nordica boho
turbo potente silencioso silenciosa fone fones ouvido headphone headset caixa som carregador cabo pilha
pilhas bateria baterias recarregaveis brinquedo brinquedos educativo educativa educativos pedagogico
pedagogica montessori boneca bonecas boneco carrinho carrinhos quebra cabeca blocos pelucias
chave chaves ferramenta ferramentas parafuso parafusos
gel shampoo condicionador perfume colonia desodorante oleo esmalte esmaltes unha unhas lixa alicate
manicure pedicure cutelaria cilios sobrancelha depilador depilacao barbeador aparador
blackout sala dormitorio banheiro varanda jardim area servico escritorio entrada lavabo closet
folheado folheada folheados banhado banhada prata ouro rodio cirurgico zirconia perola perolas cristal
cristais strass miçanga micangas
pro plus size fitness academia yoga pilates esporte esportivo esportiva corrida
ergonomico ergonomica removivel lavaveis destacavel anatomico anatomica respiravel termico
geladeira geladeiras freezer despensa armario armarios pia bancada parede porta box chuveiro vaso sanitario
sacolinha carrinho feira cozinhar organizacao
""".split())

# palavras compostas aceitas inteiras (as partes sozinhas podem nao estar na lista)
COMPOSTOS = {"meiacalca", "meiacalcas", "guardaroupa", "guardaroupas", "portatempero", "portatemperos"}


def normalizar_palavra(p: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", (p or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return "".join(c for c in t if "a" <= c <= "z")  # so letras latinas basicas: nada de numeral Unicode


PALAVRAS = {normalizar_palavra(w) for w in PALAVRAS} - {""}
CONECTORES = {normalizar_palavra(w) for w in CONECTORES}
COMPOSTOS = {normalizar_palavra(w) for w in COMPOSTOS}
