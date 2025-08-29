from __future__ import annotations
from decimal import Decimal
from typing import Dict, List, Iterable
from datetime import date

from django.shortcuts import render
from django.utils import timezone
from django.db.models import Prefetch

from core.models import Membro
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

M2M_MEMBROS_FIELD = "membros"
TRANSACAO_DATA_FIELD = "data"

def _has_field(model, field_name: str) -> bool:
    try:
        return any(f.name == field_name for f in model._meta.get_fields())
    except Exception:
        return False

def _valor_despesa_conta_corrente(v: Decimal) -> Decimal:
    # Despesa em conta corrente: valores negativos -> positivos (gasto)
    return -v if v < 0 else Decimal("0")

def _valor_despesa_cartao(v: Decimal) -> Decimal:
    # Despesa em cartão: valores positivos são gastos
    return v if v > 0 else Decimal("0")

MESES_LABEL = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]

def _init_matriz(membros: Iterable[Membro]) -> Dict[int, List[Decimal]]:
    base: Dict[int, List[Decimal]] = {}
    for m in membros:
        base[m.id] = [Decimal("0")] * 12
    return base

def _add(matriz: Dict[int, List[Decimal]], membro_id: int, mes_idx_0_11: int, valor: Decimal) -> None:
    matriz[membro_id][mes_idx_0_11] += valor

def _distribui_por_membros(obj, valor_total: Decimal, matriz: Dict[int, List[Decimal]], mes_idx_0_11: int) -> None:
    membros = list(getattr(obj, M2M_MEMBROS_FIELD).all())
    if not membros or valor_total == 0:
        return
    quota = (valor_total / Decimal(len(membros))).quantize(Decimal("0.01"))
    for m in membros:
        _add(matriz, m.id, mes_idx_0_11, quota)

def _anos_disponiveis() -> List[int]:
    # Anos com dados VISÍVEIS (oculta=False) em CC e (se existir) Cartão
    qs_cc = Transacao.objects.all()
    if _has_field(Transacao, "oculta"):
        qs_cc = qs_cc.filter(oculta=False)
    anos_cc = [d.year for d in qs_cc.dates(TRANSACAO_DATA_FIELD, "year")]

    qs_cart = Lancamento.objects.select_related("fatura")
    if _has_field(Lancamento, "oculta"):
        qs_cart = qs_cart.filter(oculta=False)
    anos_cartao = list(
        qs_cart.values_list("fatura__competencia__year", flat=True).distinct()
    )

    anos = sorted(set(anos_cc + anos_cartao), reverse=True)
    if not anos:
        anos = [timezone.localdate().year]
    return anos

def _to_rows(matriz: Dict[int, List[Decimal]], membros: List[Membro]) -> List[dict]:
    rows: List[dict] = []
    for m in membros:
        mensal = matriz[m.id]
        total = sum(mensal, Decimal("0"))
        rows.append({"membro": m, "mensal": mensal, "total": total})
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows

def _footer_totais(matriz: Dict[int, List[Decimal]]) -> dict | None:
    if not matriz:
        return None
    mensal = [Decimal("0")] * 12
    for lista in matriz.values():
        for i in range(12):
            mensal[i] += lista[i]
    total = sum(mensal, Decimal("0"))
    return {"mensal": mensal, "total": total}

def _pacote_tabela(matriz: Dict[int, List[Decimal]], membros: List[Membro]) -> dict:
    rows = _to_rows(matriz, membros)
    footer = _footer_totais(matriz) if rows else None
    return {"rows": rows, "footer": footer}

def resumo_anual(request):
    """
    Resumo anual de gastos por membro, mês a mês, respeitando ocultação:
      1) Geral (Conta Corrente + Cartão)
      2) Somente Conta Corrente
      3) Somente Cartão de Crédito
    Para cartão, usa fatura.competencia como referência de mês.
    """
    hoje = timezone.localdate()
    anos = _anos_disponiveis()
    try:
        ano = int(request.GET.get("ano") or anos[0] or hoje.year)
    except Exception:
        ano = anos[0] if anos else hoje.year

    membros = list(Membro.objects.order_by("nome"))
    if not membros:
        return render(
            request,
            "relatorios/resumo_anual.html",
            {
                "app_ns": "relatorios",
                "ano": ano,
                "anos_disponiveis": anos,
                "meses_label": MESES_LABEL,
                "geral": {"rows": [], "footer": None},
                "conta_corrente": {"rows": [], "footer": None},
                "cartao_credito": {"rows": [], "footer": None},
            },
        )

    matriz_geral = _init_matriz(membros)
    matriz_cc = _init_matriz(membros)
    matriz_cartao = _init_matriz(membros)

    # ---------------- Conta Corrente (apenas visíveis) ----------------
    transacoes = (
        Transacao.objects
        .filter(**{f"{TRANSACAO_DATA_FIELD}__year": ano})
        .filter(oculta=False)  # <<<<<<<<<<<<<<<<<<<<< aplica ocultação
        .prefetch_related(Prefetch(M2M_MEMBROS_FIELD))
    )
    for t in transacoes:
        d: date | None = getattr(t, TRANSACAO_DATA_FIELD, None)
        if not d or d.year != ano:
            continue
        mes_idx = d.month - 1
        val = _valor_despesa_conta_corrente(getattr(t, "valor", Decimal("0")))
        if val <= 0:
            continue
        _distribui_por_membros(t, val, matriz_cc, mes_idx)
        _distribui_por_membros(t, val, matriz_geral, mes_idx)

    # ---------------- Cartão (por fatura) ----------------
    lancs = (
        Lancamento.objects
        .select_related("fatura")
        .filter(fatura__competencia__year=ano)
    )
    # Só filtra se existir 'oculta' no modelo de cartão (fica compatível com hoje e com o futuro)
    if _has_field(Lancamento, "oculta"):
        lancs = lancs.filter(oculta=False)

    lancs = lancs.prefetch_related(Prefetch(M2M_MEMBROS_FIELD))

    for l in lancs:
        if not getattr(l, "fatura", None) or not l.fatura.competencia:
            continue
        comp: date = l.fatura.competencia
        if comp.year != ano:
            continue
        mes_idx = comp.month - 1
        val = _valor_despesa_cartao(getattr(l, "valor", Decimal("0")))
        if val <= 0:
            continue
        _distribui_por_membros(l, val, matriz_cartao, mes_idx)
        _distribui_por_membros(l, val, matriz_geral, mes_idx)

    contexto = {
        "app_ns": "relatorios",
        "ano": ano,
        "anos_disponiveis": anos,
        "meses_label": MESES_LABEL,
        "geral": _pacote_tabela(matriz_geral, membros),
        "conta_corrente": _pacote_tabela(matriz_cc, membros),
        "cartao_credito": _pacote_tabela(matriz_cartao, membros),
    }
    return render(request, "relatorios/resumo_anual.html", contexto)
