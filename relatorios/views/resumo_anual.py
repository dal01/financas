from __future__ import annotations
from decimal import Decimal
from datetime import date

from django.shortcuts import render
from django.utils import timezone
from django.db.models import Prefetch

from core.models import Membro
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

from relatorios.utils.gastos import valor_despesa_conta_corrente, valor_despesa_cartao
from relatorios.utils.membros import (
    init_matriz, distribui_por_membros, pacote_tabela, medias_mensais_por_membro_apenas_meses_positivos
)
from relatorios.utils.periodo import anos_disponiveis

M2M_MEMBROS_FIELD = "membros"
TRANSACAO_DATA_FIELD = "data"
MESES_LABEL = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]

def _has_field(model, field_name: str) -> bool:
    try:
        return any(f.name == field_name for f in model._meta.get_fields())
    except Exception:
        return False

def resumo_anual(request):
    """
    Resumo anual por membro (CC + Cartão), respeitando ocultas.
    CC: só despesas (negativas)
    Cartão: despesas (positivas) menos estornos/créditos (negativos)
    """
    hoje = timezone.localdate()
    anos = anos_disponiveis()
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

    matriz_geral = init_matriz(membros)
    matriz_cc = init_matriz(membros)
    matriz_cartao = init_matriz(membros)

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
        val = valor_despesa_conta_corrente(getattr(t, "valor", Decimal("0")))
        if val == 0:
            continue
        distribui_por_membros(t, val, matriz_cc, mes_idx)
        distribui_por_membros(t, val, matriz_geral, mes_idx)

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
        val = valor_despesa_cartao(getattr(l, "valor", Decimal("0")))
        if val == 0:
            continue
        distribui_por_membros(l, val, matriz_cartao, mes_idx)
        distribui_por_membros(l, val, matriz_geral, mes_idx)

    # Pacotes de tabela
    pacote_geral = pacote_tabela(matriz_geral, membros)
    pacote_cc = pacote_tabela(matriz_cc, membros)
    pacote_cartao = pacote_tabela(matriz_cartao, membros)

    # Médias por membro considerando apenas meses com valor > 0 no GERAL
    medias_por_membro = medias_mensais_por_membro_apenas_meses_positivos(matriz_geral, membros)

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
