# core/views/classificacao.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
import calendar
from typing import Any, Dict, List, Tuple

from django.db.models import Q
from django.http import HttpRequest, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.models import Categoria
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

SENTINEL_SEM_CATEGORIA = 0
IGNORAR_CATEGORIA_PAGTO_CARTAO = "Pagamentos de cartão"  # iexact

# Lista as categorias macro (sem pai) para popular filtros e modal
def _fetch_macros_for_filters():
    from core.models import Categoria
    return Categoria.objects.filter(categoria_pai__isnull=True).order_by("nome")



# =========================
# Período
# =========================
def _periodo_from_get(request: HttpRequest) -> Tuple[date, date, Dict[str, Any]]:
    today = date.today()
    modo = (request.GET.get("modo") or "ano").lower()
    try:
        ano = int(request.GET.get("ano") or today.year)
    except Exception:
        ano = today.year

    if modo == "mes":
        try:
            mes = int(request.GET.get("mes") or today.month)
            mes = 1 if mes < 1 else (12 if mes > 12 else mes)
        except Exception:
            mes = today.month
        dt_ini = date(ano, mes, 1)
        last_day = calendar.monthrange(ano, mes)[1]
        dt_fim = date(ano, mes, last_day)
        periodo_label = f"{dt_ini:%B/%Y}".capitalize()
    else:
        dt_ini = date(ano, 1, 1)
        dt_fim = date(ano, 12, 31)
        periodo_label = f"{ano}"

    return dt_ini, dt_fim, {
        "modo": modo,
        "ano": ano,
        "mes": dt_ini.month if modo == "mes" else None,
        "periodo_label": periodo_label,
    }


# =========================
# Helpers de ocultação
# =========================
def _oculta_filter_kwargs(model) -> Dict[str, bool]:
    candidates = [
        "oculta", "ocultar", "oculto",
        "oculta_manual", "ocultar_manual",
        "ignorada", "ignorar",
        "is_oculta", "is_ignorada",
    ]
    found = []
    for fname in candidates:
        try:
            model._meta.get_field(fname)
            found.append(fname)
        except Exception:
            pass
    return {f: True for f in found}


def _excluir_ocultas(qs, model):
    kwargs = _oculta_filter_kwargs(model)
    for k, v in kwargs.items():
        qs = qs.exclude(**{k: v})
    return qs


# =========================
# Query + filtros (fonte única)
# =========================
def _fetch_queryset(
    fonte: str,
    dt_ini: date,
    dt_fim: date,
    busca: str | None,
    macro_id: int | None,
    sub_id: int | None,
):
    """
    - CC: só despesas (valor < 0); exclui 'Pagamentos de cartão'
    - Cartão: somente valor > 0 (não mostra créditos/estornos)
    - Exclui registros marcados como ocultos
    - Filtros de macro/sub (macro=0 => Sem categoria)
    """
    if fonte == "cartao":
        qs = Lancamento.objects.filter(data__gte=dt_ini, data__lte=dt_fim)
        qs = _excluir_ocultas(qs, Lancamento)
        qs = qs.filter(valor__gt=0)  # não mostrar negativos
        if busca:
            qs = qs.filter(Q(descricao__icontains=busca))
    else:
        qs = Transacao.objects.filter(data__gte=dt_ini, data__lte=dt_fim)
        qs = _excluir_ocultas(qs, Transacao)
        qs = qs.filter(valor__lt=0)  # apenas despesas
        qs = qs.exclude(categoria__nome__iexact=IGNORAR_CATEGORIA_PAGTO_CARTAO)
        if busca:
            qs = qs.filter(Q(descricao__icontains=busca))

    if macro_id is not None:
        if macro_id == SENTINEL_SEM_CATEGORIA:
            qs = qs.filter(categoria__isnull=True)
        else:
            qs = qs.filter(Q(categoria_id=macro_id) | Q(categoria__categoria_pai_id=macro_id))

    if sub_id is not None:
        qs = qs.filter(categoria_id=sub_id)

    qs = qs.select_related("categoria", "categoria__categoria_pai").order_by(
        "categoria__categoria_pai__nome",
        "categoria__nome",
        "-data",
        "-id",
    )
    return qs


def _amount_for_item(o, fonte: str) -> Decimal:
    """Valor positivo para somatório."""
    val = Decimal(o.valor or 0)
    if fonte == "cc":
        # valor < 0; somar como positivo
        return val.copy_abs()
    # cartão: já filtrado valor > 0
    return val


# =========================
# Agrupamento
# =========================
def _build_groups(objs, fonte: str):
    """
    Retorna:
    [
      {
        "macro_id": ...,
        "macro_nome": ...,
        "total_macro": Decimal,
        "subs": [
          { "sub_id": ..., "sub_nome": ..., "total_sub": Decimal, "items": [obj, ...] }
        ]
      }, ...
    ]
    """
    macros: Dict[int, Dict[str, Any]] = {}

    for o in objs:
        cat = getattr(o, "categoria", None)
        if cat is None:
            macro_id = SENTINEL_SEM_CATEGORIA
            macro_nome = "Sem categoria"
            sub_id = None
            sub_nome = "—"
        else:
            if cat.categoria_pai_id is None:
                macro_id = cat.id
                macro_nome = cat.nome
                sub_id = cat.id
                sub_nome = cat.nome
            else:
                macro_id = cat.categoria_pai_id
                macro_nome = cat.categoria_pai.nome
                sub_id = cat.id
                sub_nome = cat.nome

        m = macros.setdefault(macro_id, {
            "macro_id": macro_id,
            "macro_nome": macro_nome,
            "total_macro": Decimal("0"),
            "subs": {},
        })
        s = m["subs"].setdefault(sub_id, {
            "sub_id": sub_id,
            "sub_nome": sub_nome,
            "total_sub": Decimal("0"),
            "items": [],
        })
        s["items"].append(o)

        amt = _amount_for_item(o, fonte)
        s["total_sub"] += amt
        m["total_macro"] += amt

    macro_list: List[Dict[str, Any]] = []
    for m in macros.values():
        subs_list = list(m["subs"].values())
        subs_list.sort(key=lambda x: (x["sub_nome"] or "").lower())
        macro_list.append({
            "macro_id": m["macro_id"],
            "macro_nome": m["macro_nome"],
            "total_macro": m["total_macro"],
            "subs": subs_list,
        })
    macro_list.sort(key=lambda m: (m["macro_nome"] or "").lower())
    return macro_list


# =========================
# Unificação CC + Cartão
# =========================
def _fetch_queryset_single(fonte: str, dt_ini, dt_fim, busca, macro_id, sub_id):
    return _fetch_queryset(fonte, dt_ini, dt_fim, busca, macro_id, sub_id)


def _build_groups_from_multiple(qs_cc, qs_cartao):
    all_objs = list(qs_cc) + list(qs_cartao)
    # Para soma correta, o _amount_for_item precisa saber a fonte,
    # mas ao unificar não saberemos item a item. Solução:
    # - já transformar 'valor' dos itens de CC em positivo antes de unificar
    #   sem alterar o objeto original (criamos um atributo transient _valor_abs).
    #   Para simplificar, vamos chamar _build_groups duas vezes e somar depois.
    # Alternativa simples: duplicar lógica de soma aqui:

    macros: Dict[int, Dict[str, Any]] = {}

    # Helper interno para acumular
    def push_item(o, fonte_tag: str):
        cat = getattr(o, "categoria", None)
        if cat is None:
            macro_id = SENTINEL_SEM_CATEGORIA
            macro_nome = "Sem categoria"
            sub_id = None
            sub_nome = "—"
        else:
            if cat.categoria_pai_id is None:
                macro_id = cat.id
                macro_nome = cat.nome
                sub_id = cat.id
                sub_nome = cat.nome
            else:
                macro_id = cat.categoria_pai_id
                macro_nome = cat.categoria_pai.nome
                sub_id = cat.id
                sub_nome = cat.nome

        m = macros.setdefault(macro_id, {
            "macro_id": macro_id,
            "macro_nome": macro_nome,
            "total_macro": Decimal("0"),
            "subs": {},
        })
        s = m["subs"].setdefault(sub_id, {
            "sub_id": sub_id,
            "sub_nome": sub_nome,
            "total_sub": Decimal("0"),
            "items": [],
        })
        s["items"].append(o)

        val = Decimal(o.valor or 0)
        if fonte_tag == "cc":
            val = val.copy_abs()
        s["total_sub"] += val
        m["total_macro"] += val

    for o in qs_cc:
        push_item(o, "cc")
    for o in qs_cartao:
        push_item(o, "cartao")

    macro_list: List[Dict[str, Any]] = []
    for m in macros.values():
        subs_list = list(m["subs"].values())
        subs_list.sort(key=lambda x: (x["sub_nome"] or "").lower())
        macro_list.append({
            "macro_id": m["macro_id"],
            "macro_nome": m["macro_nome"],
            "total_macro": m["total_macro"],
            "subs": subs_list,
        })
    macro_list.sort(key=lambda m: (m["macro_nome"] or "").lower())
    return macro_list


# =========================
# View principal (exportada)
# =========================
def classificacao_gastos(request: HttpRequest):
    fonte = (request.GET.get("fonte") or "todas").lower()
    if fonte not in ("cc", "cartao", "todas"):
        fonte = "todas"

    busca = (request.GET.get("busca") or "").strip()
    dt_ini, dt_fim, ctx_periodo = _periodo_from_get(request)

    def parse_int_or_none(v: str | None):
        if not v:
            return None
        try:
            return int(v)
        except Exception:
            return None

    macro_id = parse_int_or_none(request.GET.get("macro_id"))
    sub_id = parse_int_or_none(request.GET.get("sub_id"))

    if fonte == "todas":
        qs_cc = _fetch_queryset_single("cc", dt_ini, dt_fim, busca, macro_id, sub_id)
        qs_cartao = _fetch_queryset_single("cartao", dt_ini, dt_fim, busca, macro_id, sub_id)
        grupos = _build_groups_from_multiple(qs_cc, qs_cartao)
    else:
        qs = _fetch_queryset_single(fonte, dt_ini, dt_fim, busca, macro_id, sub_id)
        grupos = _build_groups(qs, fonte)

    macros = _fetch_macros_for_filters()

    anos_disponiveis = list(range(date.today().year - 4, date.today().year + 1))
    meses = [
        (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"),
        (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
        (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
    ]

    context = {
        "title": "Classificação de Gastos",
        "fonte": fonte,
        "busca": busca,
        **ctx_periodo,
        "anos_disponiveis": anos_disponiveis,
        "meses": meses,
        "macros": macros,
        "macro_id_sel": macro_id,
        "sub_id_sel": sub_id,
        "grupos": grupos,
    }
    return render(request, "classificacao/gastos.html", context)


# =========================
# AJAX: carregar subcategorias
# =========================
@require_http_methods(["GET"])
def carregar_subcategorias_ajax(request: HttpRequest):
    macro_id = request.GET.get("macro_id")
    try:
        macro_id_int = int(macro_id)
    except Exception:
        return JsonResponse({"items": []})

    if macro_id_int == SENTINEL_SEM_CATEGORIA:  # 0 => sem categoria
        return JsonResponse({"items": []})

    subs = Categoria.objects.filter(categoria_pai_id=macro_id_int).order_by("nome")
    items = [{"id": c.id, "nome": c.nome} for c in subs]
    return JsonResponse({"items": items})


# =========================
# AJAX: atribuir categoria em lote
# =========================
@require_http_methods(["POST"])
def atribuir_categoria_ajax(request: HttpRequest):
    fonte = (request.POST.get("fonte") or "").lower()
    ids_raw = request.POST.get("ids") or ""
    categoria_id_raw = request.POST.get("categoria_id")  # '' => limpar

    if fonte not in ("cc", "cartao"):
        return HttpResponseBadRequest("Fonte inválida")

    try:
        ids = [int(x) for x in ids_raw.split(",") if x.strip()]
    except Exception:
        return HttpResponseBadRequest("IDs inválidos")
    if not ids:
        return HttpResponseBadRequest("Nenhum ID informado")

    categoria_id = None
    if categoria_id_raw not in (None, ""):
        try:
            categoria_id = int(categoria_id_raw)
        except Exception:
            return HttpResponseBadRequest("categoria_id inválido")

    Model = Lancamento if fonte == "cartao" else Transacao

    if categoria_id is not None and not Categoria.objects.filter(id=categoria_id).exists():
        return HttpResponseBadRequest("Categoria inexistente")

    updated = Model.objects.filter(id__in=ids).update(categoria_id=categoria_id)
    return JsonResponse({"ok": True, "updated": updated})
