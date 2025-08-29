from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
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
    # CC: despesas são negativas -> transformamos em positivo; créditos/entradas ignorados
    return -v if v < 0 else Decimal("0")

def _valor_despesa_cartao(v: Decimal) -> Decimal:
    # Cartão: manter o sinal para que estornos (negativos) abatam o total
    return Decimal(v or 0)

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
    # Ajuste de resíduo para fechar exatamente o total
    resto = valor_total - quota * len(membros)
    for i, m in enumerate(membros):
        val = quota + (resto if i == len(membros) - 1 else Decimal("0"))
        _add(matriz, m.id, mes_idx_0_11, val)

def _anos_disponiveis() -> List[int]:
    qs_cc = Transacao.objects.all()
    if _has_field(Transacao, "oculta"):
        qs_cc = qs_cc.filter(oculta=False)
    anos_cc = [d.year for d in qs_cc.dates(TRANSACAO_DATA_FIELD, "year")]

    qs_cart = Lancamento.objects.select_related("fatura")
    if _has_field(Lancamento, "oculta"):
        qs_cart = qs_cart.filter(oculta=False)
    anos_cartao = list(qs_cart.values_list("fatura__competencia__year", flat=True).distinct())

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

def _medias_mensais_por_membro_apenas_meses_positivos(
    matriz_geral: Dict[int, List[Decimal]],
    membros: List[Membro],
) -> List[dict]:
    """
    Para cada membro, calcula:
      - total_ano = soma dos 12 meses
      - meses_positivos = quantidade de meses com valor > 0
      - media = total_ano / meses_positivos (se meses_positivos > 0; senão 0)
    Retorna lista com {membro, media, meses_positivos, total}.
    """
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
    # Ordena por maior média
    saida.sort(key=lambda x: x["media"], reverse=True)
    return saida

def resumo_anual(request):
    """
    Resumo anual por membro (CC + Cartão), respeitando ocultas.
    CC: só despesas (negativas)
    Cartão: despesas (positivas) menos estornos/créditos (negativos)
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
                "medias_por_membro": [],
            },
        )

    matriz_geral = _init_matriz(membros)
    matriz_cc = _init_matriz(membros)
    matriz_cartao = _init_matriz(membros)

    # -------- Conta Corrente (ocultas=False se existir campo) --------
    transacoes = (
        Transacao.objects
        .filter(**{f"{TRANSACAO_DATA_FIELD}__year": ano})
    )
    if _has_field(Transacao, "oculta"):
        transacoes = transacoes.filter(oculta=False)
    transacoes = transacoes.prefetch_related(Prefetch(M2M_MEMBROS_FIELD))

    for t in transacoes:
        d: date | None = getattr(t, TRANSACAO_DATA_FIELD, None)
        if not d or d.year != ano:
            continue
        mes_idx = d.month - 1
        val = _valor_despesa_conta_corrente(getattr(t, "valor", Decimal("0")))
        if val == 0:
            continue
        _distribui_por_membros(t, val, matriz_cc, mes_idx)
        _distribui_por_membros(t, val, matriz_geral, mes_idx)

    # -------- Cartão (por fatura; ocultas se existir) --------
    lancs = (
        Lancamento.objects
        .select_related("fatura")
        .filter(fatura__competencia__year=ano)
    )
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
        # NET: positivo = gasto; negativo = estorno (subtrai)
        val = _valor_despesa_cartao(getattr(l, "valor", Decimal("0")))
        if val == 0:
            continue
        _distribui_por_membros(l, val, matriz_cartao, mes_idx)
        _distribui_por_membros(l, val, matriz_geral, mes_idx)

    # Pacotes de tabela
    pacote_geral = _pacote_tabela(matriz_geral, membros)
    pacote_cc = _pacote_tabela(matriz_cc, membros)
    pacote_cartao = _pacote_tabela(matriz_cartao, membros)

    # Médias por membro considerando apenas meses com valor > 0 no GERAL
    medias_por_membro = _medias_mensais_por_membro_apenas_meses_positivos(matriz_geral, membros)

    contexto = {
        "app_ns": "relatorios",
        "ano": ano,
        "anos_disponiveis": anos,
        "meses_label": MESES_LABEL,
        "geral": pacote_geral,
        "conta_corrente": pacote_cc,
        "cartao_credito": pacote_cartao,
        "medias_por_membro": medias_por_membro,
    }
    return render(request, "relatorios/resumo_anual.html", contexto)
