from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Iterable
from core.models import Membro

def init_matriz(membros: Iterable[Membro]) -> Dict[int, List[Decimal]]:
    base: Dict[int, List[Decimal]] = {}
    for m in membros:
        base[m.id] = [Decimal("0")] * 12
    return base

def add(matriz: Dict[int, List[Decimal]], membro_id: int, mes_idx_0_11: int, valor: Decimal) -> None:
    matriz[membro_id][mes_idx_0_11] += valor

def distribui_por_membros(obj, valor_total: Decimal, matriz: Dict[int, List[Decimal]], mes_idx_0_11: int) -> None:
    membros = list(getattr(obj, "membros").all())
    if not membros or valor_total == 0:
        return
    quota = (valor_total / Decimal(len(membros))).quantize(Decimal("0.01"))
    resto = valor_total - quota * len(membros)
    for i, m in enumerate(membros):
        val = quota + (resto if i == len(membros) - 1 else Decimal("0"))
        add(matriz, m.id, mes_idx_0_11, val)

def to_rows(matriz: Dict[int, List[Decimal]], membros: List[Membro]) -> List[dict]:
    rows: List[dict] = []
    for m in membros:
        mensal = matriz[m.id]
        total = sum(mensal, Decimal("0"))
        rows.append({"membro": m, "mensal": mensal, "total": total})
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows

def footer_totais(matriz: Dict[int, List[Decimal]]) -> dict | None:
    if not matriz:
        return None
    mensal = [Decimal("0")] * 12
    for lista in matriz.values():
        for i in range(12):
            mensal[i] += lista[i]
    total = sum(mensal, Decimal("0"))
    return {"mensal": mensal, "total": total}

def pacote_tabela(matriz: Dict[int, List[Decimal]], membros: List[Membro]) -> dict:
    rows = to_rows(matriz, membros)
    footer = footer_totais(matriz) if rows else None
    return {"rows": rows, "footer": footer}

def medias_mensais_por_membro_apenas_meses_positivos(
    matriz_geral: Dict[int, List[Decimal]],
    membros: List[Membro],
) -> List[dict]:
    saida = []
    TWO = Decimal("0.01")
    for m in membros:
        mensal = matriz_geral[m.id]
        total = sum(mensal, Decimal("0"))
        meses_positivos = sum(1 for v in mensal if v > 0)
        if meses_positivos > 0:
            media = (total / Decimal(meses_positivos)).quantize(TWO, rounding=ROUND_HALF_UP)
        else:
            media = Decimal("0.00")
        saida.append({
            "membro": m,
            "media": media,
            "meses_positivos": meses_positivos,
            "total": total,
        })
    saida.sort(key=lambda x: x["media"], reverse=True)
    return saida