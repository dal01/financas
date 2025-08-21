import re
from unidecode import unidecode

PADROES_LIXO = [
    r'\bPARC\s*\d{1,2}\s*/\s*\d{1,2}\b',  # PARC 02/12
    r'\b\d{1,2}/\d{1,2}\b',               # 02/12
    r'\bBRASIL(IA)?\b',
    r'\bBR\b',
    r'\bSAO\s*PAULO\b',
    r'\bRIO\s*DE\s*JANEIRO\b',
    r'\b[ACDFGHJLMOPRSTUVWXYZ]{2}\b',     # UFs; ajuste se quiser
]

def normalizar(texto: str) -> str:
    t = unidecode((texto or '').upper())
    t = re.sub(r'[^A-Z0-9 ]+', ' ', t)  # limpa simbolos
    for p in PADROES_LIXO:
        t = re.sub(p, ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t
