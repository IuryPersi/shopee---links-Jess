"""Atalho para subir o painel de qualquer pasta: py -3.12 "W:/Robo Shopee/painel.py" """
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

from robo.painel import main  # noqa: E402

main()
