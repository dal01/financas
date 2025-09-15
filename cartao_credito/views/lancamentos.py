from __future__ import annotations
from datetime import date
from typing import Optional

from django.core.paginator import Paginator
from django.db.models import Q, Sum, Value, DecimalField
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import render

from core.models import Membro, InstituicaoFinanceira
from ..models import Cartao, FaturaCartao, Lancamento
from cartao_credito.utils.helpers import (
    lancamentos_visiveis,
    lancamentos_periodo,
    lancamentos_membro,
)


def _parse_ym(s: Optional[str]) -> Optional[date]:
    """Converte 'YYYY-MM' em date(YYYY, MM, 1). Retorna None se inválido/vazio."""
    if not s:
        return None
    try:
        y, m = s.split("-")
        y, m = int(y), int(m)
        if 1 <= m <= 12:
            return date(y, m, 1)
    except Exception:
        pass
    return None


def _primeiro_dia_mes_atual() -> date:
    hoje = date.today()
    return hoje.replace(day=1)


def lista_lancamentos(request):
    """
    Lista global de lançamentos com filtros + cards de totais por:
      - Membro (titular do cartão)
      - Instituição
      - Cartão (Instituição + final + bandeira)
    Por padrão, inicia no mês atual se nenhum filtro.
    """
    qs = (
        Lancamento.objects
        .select_related("fatura", "fatura__cartao", "fatura__cartao__instituicao", "fatura__cartao__membro")
        .prefetch_related("membros")
    )

    # ---- filtros ----
    cartao_id = request.GET.get("cartao") or ""
    instituicao_id = request.GET.get("instituicao") or ""
    membro_id = request.GET.get("membro") or ""
    secao = request.GET.get("secao") or ""
    ym = _parse_ym(request.GET.get("ym"))
    ym_from = _parse_ym(request.GET.get("ym_from"))
    ym_to = _parse_ym(request.GET.get("ym_to"))
    q = (request.GET.get("q") or "").strip()

    # por padrão, fixa mês atual se nenhum range especificado
    if not ym and not ym_from and not ym_to:
        ym = _primeiro_dia_mes_atual()

    if cartao_id:
        qs = qs.filter(fatura__cartao_id=cartao_id)
    if instituicao_id:
        qs = qs.filter(fatura__cartao__instituicao_id=instituicao_id)
    if membro_id:
        # titular do cartão OU membro(s) atribuídos no lançamento
        qs = qs.filter(
            Q(fatura__cartao__membro_id=membro_id) |
            Q(membros__id=membro_id)
        ).distinct()
    if secao:
        qs = qs.filter(secao=secao)

    # Use helpers para filtrar período
    if ym:
        qs = lancamentos_periodo(qs, ym, ym)
    else:
        if ym_from or ym_to:
            qs = lancamentos_periodo(qs, ym_from, ym_to)

    if q:
        qs = qs.filter(
            Q(descricao__icontains=q) |
            Q(cidade__icontains=q) |
            Q(pais__icontains=q)
        )

    # Use helper para ocultas
    qs = lancamentos_visiveis(qs)

    qs = qs.order_by("-data", "-id")

    # paginação
    paginator = Paginator(qs, 100)
    page = paginator.get_page(request.GET.get("page"))

    # agregado geral
    soma_valor = qs.aggregate(
        s=Coalesce(Sum("valor"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2))
    )["s"]

    # ---- agregações para os cards ----
    # 1) Por Membro (titular do cartão)
    por_membro = (
        qs.values("fatura__cartao__membro__id", "fatura__cartao__membro__nome")
          .annotate(soma=Coalesce(Sum("valor"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
          .order_by("-soma", "fatura__cartao__membro__nome")
    )

    # 2) Por Instituição
    por_instituicao = (
        qs.values("fatura__cartao__instituicao__id", "fatura__cartao__instituicao__nome")
          .annotate(soma=Coalesce(Sum("valor"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
          .order_by("-soma", "fatura__cartao__instituicao__nome")
    )

    # 3) Por Cartão
    por_cartao = (
        qs.values(
            "fatura__cartao__id",
            "fatura__cartao__instituicao__nome",
            "fatura__cartao__cartao_final",
            "fatura__cartao__bandeira",
        )
          .annotate(soma=Coalesce(Sum("valor"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
          .order_by("-soma", "fatura__cartao__instituicao__nome", "fatura__cartao__cartao_final")
    )

    ctx = {
        "page_obj": page,
        "soma_valor": soma_valor,
        "cartoes": Cartao.objects.select_related("instituicao", "membro").order_by("instituicao__nome", "cartao_final"),
        "instituicoes": InstituicaoFinanceira.objects.order_by("nome"),
        "membros": Membro.objects.order_by("nome"),
        "filtros": {
            "cartao": cartao_id,
            "instituicao": instituicao_id,
            "membro": membro_id,
            "secao": secao,
            # refletir a escolha (ou o default do mês atual) no form:
            "ym": (request.GET.get("ym") or (ym.strftime("%Y-%m") if ym else "")),
            "ym_from": request.GET.get("ym_from") or "",
            "ym_to": request.GET.get("ym_to") or "",
            "q": q,
        },
        # dados para os cards
        "aggs": {
            "por_membro": list(por_membro),
            "por_instituicao": list(por_instituicao),
            "por_cartao": list(por_cartao),
        },
    }
    return render(request, "cartao_credito/lancamentos_lista.html", ctx)
