# core/views/classificacao.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional, Dict

from django.core.paginator import Paginator
from django.db.models import F, Value, DecimalField, Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from core.models import Categoria
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento


# =========================
# COLUNAS (ajuste aqui se mudar nomes dos campos)
# =========================

# Transação (conta corrente)
TX_COL_DATA = "data"
TX_COL_DESC = "descricao"
TX_COL_VAL = "valor"
TX_COL_CAT = "categoria"

# Lançamento (cartão)
LC_COL_DATA = "data"       # <- no seu modelo é 'data'
LC_COL_DESC = "descricao"
LC_COL_VAL = "valor"
LC_COL_CAT = "categoria"


# =========================
# HELPERS
# =========================
def _get_param(request, name: str, default: str = "") -> str:
    return (request.GET.get(name) or request.POST.get(name) or default).strip()


def _filtro_busca(qs, campo_desc: str, termo: str):
    if termo:
        qs = qs.filter(Q(**{f"{campo_desc}__icontains": termo}))
    return qs


def _paginar(request, qs, per_page: int = 50):
    p = Paginator(qs, per_page)
    page = request.GET.get("page") or 1
    return p.get_page(page)


def _oculta_filter_kwargs(model) -> Optional[Dict[str, Any]]:
    """
    Descobre automaticamente um possível campo booleano de 'ocultação'
    no model e retorna kwargs para filtrar/excluir.
    Nomes comuns suportados: ocultar, oculta, oculto, ignorada, ignorar, is_oculta, is_ignorada.
    """
    candidate_fields = [
        "ocultar", "oculta", "oculto",
        "ignorada", "ignorar",
        "is_oculta", "is_ignorada",
    ]
    for fname in candidate_fields:
        try:
            model._meta.get_field(fname)
            return {fname: True}
        except Exception:
            continue
    return None


def _excluir_ocultas(qs, model):
    """
    Aplica exclude em cima do campo de 'ocultação' se existir no model.
    Caso não exista, retorna o queryset sem alteração.
    """
    kwargs = _oculta_filter_kwargs(model)
    return qs.exclude(**kwargs) if kwargs else qs


# =========================
# QUERYSETS BASE
# =========================
def qs_transacoes(request):
    """Transações sem categoria por padrão (fonte=cc)."""
    qs = Transacao.objects.all()

    # Ignora transações marcadas como 'ocultas' (se o campo existir)
    qs = _excluir_ocultas(qs, Transacao)

    # Apenas sem categoria
    qs = qs.filter(**{f"{TX_COL_CAT}__isnull": True})

    # Busca por descrição (opcional)
    qs = _filtro_busca(qs, TX_COL_DESC, _get_param(request, "busca"))

    # Valor para exibição
    qs = qs.annotate(
        valor_despesa=Coalesce(F(TX_COL_VAL), Value(0, output_field=DecimalField())),
    )

    # Ordene ANTES de paginar
    return qs.order_by(f"-{TX_COL_DATA}", "-id")


def qs_lancamentos(request):
    """Lançamentos sem categoria por padrão (fonte=cartao)."""
    qs = Lancamento.objects.all()

    # Ignora lançamentos marcados como 'ocultos' (se o campo existir)
    qs = _excluir_ocultas(qs, Lancamento)

    # Apenas sem categoria
    qs = qs.filter(**{f"{LC_COL_CAT}__isnull": True})

    # Busca
    qs = _filtro_busca(qs, LC_COL_DESC, _get_param(request, "busca"))

    qs = qs.annotate(
        valor_despesa=Coalesce(F(LC_COL_VAL), Value(0, output_field=DecimalField())),
    )
    return qs.order_by(f"-{LC_COL_DATA}", "-id")


# =========================
# VIEW PRINCIPAL
# =========================
@ensure_csrf_cookie
@require_http_methods(["GET"])
def classificacao_gastos(request):
    """
    Inbox de classificação com duas abas:
    - fonte=cc (conta corrente)
    - fonte=cartao (cartão de crédito)
    """
    fonte = _get_param(request, "fonte", "cc")
    per_page = int(_get_param(request, "pp", "50") or 50)

    macros = Categoria.objects.filter(nivel=1).order_by("nome")

    if fonte == "cartao":
        page_obj = _paginar(request, qs_lancamentos(request), per_page)
        cols = dict(col_data=LC_COL_DATA, col_desc=LC_COL_DESC, col_val="valor_despesa", col_id="id")
        titulo = "Classificação – Cartão de Crédito"
    else:
        page_obj = _paginar(request, qs_transacoes(request), per_page)
        cols = dict(col_data=TX_COL_DATA, col_desc=TX_COL_DESC, col_val="valor_despesa", col_id="id")
        titulo = "Classificação – Conta Corrente"

    ctx = {
        "fonte": fonte,
        "page_obj": page_obj,
        "cols": cols,
        "macros": macros,
        "busca": _get_param(request, "busca"),
        "per_page": per_page,
        "title": titulo,
    }
    return render(request, "classificacao/gastos.html", ctx)


# =========================
# AJAX: carregar subcategorias de uma macro
# =========================
@require_http_methods(["GET"])
def carregar_subcategorias_ajax(request):
    macro_id = _get_param(request, "macro_id")
    if not macro_id:
        return JsonResponse({"items": []})
    items = list(
        Categoria.objects.filter(categoria_pai_id=macro_id, nivel=2)
        .order_by("nome")
        .values("id", "nome")
    )
    return JsonResponse({"items": items})


# =========================
# AJAX: atribuir categoria (lote)
# =========================
@require_http_methods(["POST"])
def atribuir_categoria_ajax(request):
    """
    body:
      fonte: 'cc' | 'cartao'
      ids: '1,2,3'
      categoria_id: '123'
    """
    fonte = _get_param(request, "fonte")
    ids_str = _get_param(request, "ids")
    categoria_id = _get_param(request, "categoria_id")

    if not (fonte and ids_str and categoria_id):
        return HttpResponseBadRequest("Parâmetros inválidos.")

    try:
        cat = Categoria.objects.get(pk=int(categoria_id))
    except Exception:
        return HttpResponseBadRequest("Categoria inválida.")

    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        return HttpResponseBadRequest("Nenhum ID informado.")

    if fonte == "cc":
        count = Transacao.objects.filter(pk__in=ids).update(**{TX_COL_CAT: cat})
    elif fonte == "cartao":
        count = Lancamento.objects.filter(pk__in=ids).update(**{LC_COL_CAT: cat})
    else:
        return HttpResponseBadRequest("Fonte inválida.")

    return JsonResponse({"ok": True, "atualizados": count})
