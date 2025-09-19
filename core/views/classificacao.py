# core/views/classificacao.py
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Dict, List, Tuple, Optional
from datetime import datetime, date

from django.core.paginator import Paginator
from django.db.models import Q, DateTimeField
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_http_methods

from core.models import Categoria, Membro
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento
from conta_corrente.utils.helpers import atribuir_membro as atribuir_membro_cc
from cartao_credito.utils.helpers import atribuir_membro as atribuir_membro_cartao


# =========================
# Campos usados
# =========================
TX_COL_DATA = "data"
TX_COL_DESC = "descricao"
TX_COL_VAL  = "valor"
TX_COL_CAT  = "categoria"

LC_COL_DATA = "data"
LC_COL_DESC = "descricao"
LC_COL_VAL  = "valor"
LC_COL_CAT  = "categoria"


# =========================
# Helpers
# =========================
def _has_field(model, field_name: str) -> bool:
    try:
        return any(f.name == field_name for f in model._meta.get_fields())
    except Exception:
        return False


def _is_datetime_field(model, field_name: str) -> bool:
    """
    True se o campo for DateTimeField; False caso contrário (inclui DateField).
    """
    try:
        f = model._meta.get_field(field_name)
        return isinstance(f, DateTimeField)
    except Exception:
        return False


def _apenas_visiveis_qs(qs):
    if _has_field(qs.model, "oculta"):
        qs = qs.exclude(oculta=True)
    return qs


def _parse_busca(queryset, busca: str, campos: Iterable[str]):
    if not busca:
        return queryset
    termos = [t.strip() for t in busca.split() if t.strip()]
    for t in termos:
        cond = Q()
        for campo in campos:
            cond |= Q(**{f"{campo}__icontains": t})
        queryset = queryset.filter(cond)
    return queryset


def _ordenar(qs, default: str | Iterable[str] = "-data"):
    try:
        # já é lista/tupla?
        if isinstance(default, (list, tuple)):
            return qs.order_by(*default)

        # string com vírgulas? quebra em partes
        if isinstance(default, str) and "," in default:
            partes = [p.strip() for p in default.split(",") if p.strip()]
            if partes:
                return qs.order_by(*partes)

        # string simples
        return qs.order_by(default)
    except Exception:
        return qs



def _filtrar_periodo(qs, data_ini: Optional[str], data_fim: Optional[str], campo_data: str):
    """
    Aceita strings 'YYYY-MM-DD' e aplica filtro correto:
      - Se campo for DateTimeField -> usa __date__gte/__date__lte
      - Se for DateField -> usa __gte/__lte direto
    """
    is_dt = _is_datetime_field(qs.model, campo_data)
    prefix = f"{campo_data}__date" if is_dt else campo_data

    if data_ini:
        try:
            datetime.strptime(data_ini, "%Y-%m-%d")
            qs = qs.filter(**{f"{prefix}__gte": data_ini})
        except Exception:
            pass
    if data_fim:
        try:
            datetime.strptime(data_fim, "%Y-%m-%d")
            qs = qs.filter(**{f"{prefix}__lte": data_fim})
        except Exception:
            pass
    return qs


# ====== Helpers para competência da fatura (cartão) ======
def _primeiro_dia_do_mes(d: date) -> date:
    return date(d.year, d.month, 1)

def _parse_data(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _filtrar_periodo_cartao_por_fatura(qs, data_ini: Optional[str], data_fim: Optional[str]):
    """
    Aplica período usando a competência da fatura (YYYY-MM-01), não a data da compra.
    Model: FaturaCartao.competencia é DateField (1º dia do mês).
    """
    d1 = _parse_data(data_ini)
    d2 = _parse_data(data_fim)
    if d1:
        d1 = _primeiro_dia_do_mes(d1)
        qs = qs.filter(fatura__competencia__gte=d1)
    if d2:
        d2 = _primeiro_dia_do_mes(d2)
        qs = qs.filter(fatura__competencia__lte=d2)
    return qs


# =========================
# Normalização (gastos)
# =========================
def gasto_normalizado_transacao(v: Decimal) -> Decimal:
    # CC: negativos = despesa (→ positivo), positivos = receita (→ 0)
    v = Decimal(v or 0)
    return -v if v < 0 else Decimal("0")


def gasto_normalizado_lancamento(v: Decimal) -> Decimal:
    # Cartão: positivos = despesa; negativos = estorno (abate)
    return Decimal(v or 0)


# =========================
# Agrupamento Macro → Sub → Itens
# =========================
def _group_por_categoria(
    itens: Iterable,
    fonte: str,
    col_data: str,
    col_desc: str,
    col_val: str,
    col_cat: str,
) -> Tuple[List[Dict], Decimal]:
    total_geral = Decimal("0")
    macros: Dict[int, Dict] = {}  # macro_id -> {id,nome,total,subs:{sub_id:{...}}}

    for obj in itens:
        valor = getattr(obj, col_val, Decimal("0")) or Decimal("0")
        gasto = gasto_normalizado_transacao(valor) if fonte == "cc" else gasto_normalizado_lancamento(valor)

        cat: Optional[Categoria] = getattr(obj, col_cat, None)
        if cat is None:
            macro_id, macro_nome = 0, "Sem categoria"
            sub_id, sub_nome = 0, "Sem subcategoria"
        else:
            if cat.nivel == 1:
                macro_id, macro_nome = cat.id, cat.nome
                sub_id, sub_nome = 0, "Sem subcategoria"
            else:
                pai = cat.categoria_pai
                macro_id, macro_nome = (pai.id, pai.nome) if pai else (0, "Sem categoria")
                sub_id, sub_nome = cat.id, cat.nome

        m = macros.setdefault(macro_id, {"id": macro_id, "nome": macro_nome, "total": Decimal("0"), "subs": {}})
        s = m["subs"].setdefault(sub_id, {"id": sub_id, "nome": sub_nome, "total": Decimal("0"), "itens": []})

        s["itens"].append(obj)
        s["total"] += gasto
        m["total"] += gasto
        total_geral += gasto

    out: List[Dict] = []
    for m in macros.values():
        subs_list = list(m["subs"].values())
        subs_list.sort(key=lambda x: (x["total"], x["nome"]), reverse=True)
        out.append({"id": m["id"], "nome": m["nome"], "total": m["total"], "subcats": subs_list})
    out.sort(key=lambda x: (x["total"], x["nome"]), reverse=True)
    return out, total_geral


# =========================
# VIEW
# =========================
@require_http_methods(["GET"])
def classificacao(request: HttpRequest) -> HttpResponse:
    """
    Filtros: fonte, período (data_ini/data_fim), categoria_id (macro), subcategoria_id, busca, ordering.
    Renderiza macro sempre visível; sub sempre visível com subtotal; collapse nos itens (Bootstrap).

    OBS: Para 'cartao', o período é aplicado pela **competência da fatura** (não pela data da compra).
    """
    fonte = (request.GET.get("fonte") or "cc").lower().strip()
    busca = (request.GET.get("busca") or "").strip()
    categoria_id = request.GET.get("categoria_id")
    subcategoria_id = request.GET.get("subcategoria_id")
    membro_id = request.GET.get("membro_id")

    if fonte == "cartao":
        ordering = (request.GET.get("ordering") or "-fatura__competencia,-data").strip()
    else:
        ordering = (request.GET.get("ordering") or "-data").strip()

    hoje = date.today()
    primeiro_dia_ano = date(hoje.year, 1, 1)
    data_ini = (request.GET.get("data_ini") or primeiro_dia_ano.strftime("%Y-%m-%d")).strip()
    data_fim = (request.GET.get("data_fim") or hoje.strftime("%Y-%m-%d")).strip()

    categorias_macro = Categoria.objects.filter(nivel=1).order_by("nome")
    membros = list(Membro.objects.order_by("nome"))

    # ---------- Conta Corrente ----------
    if fonte == "cc":
        qs = Transacao.objects.all()
        qs = _apenas_visiveis_qs(qs)
        qs = _filtrar_periodo(qs, data_ini, data_fim, TX_COL_DATA)
        qs = qs.filter(valor__lt=0)

        if categoria_id is not None and categoria_id != "":
            if categoria_id == "0":
                qs = qs.filter(**{f"{TX_COL_CAT}__isnull": True})
            else:
                qs = qs.filter(
                    Q(**{f"{TX_COL_CAT}_id": categoria_id}) |
                    Q(**{f"{TX_COL_CAT}__categoria_pai_id": categoria_id})
                )

        if subcategoria_id:
            qs = qs.filter(**{f"{TX_COL_CAT}_id": subcategoria_id})

        if membro_id:
            qs = qs.filter(membros__id=membro_id)

        qs = _parse_busca(qs, busca, campos=[TX_COL_DESC])
        qs = _ordenar(qs, default=ordering)

        categorias_group, total_geral = _group_por_categoria(
            qs, "cc", TX_COL_DATA, TX_COL_DESC, TX_COL_VAL, TX_COL_CAT
        )

        ctx = {
            "fonte": "cc",
            "busca": busca,
            "categoria_id": categoria_id,
            "subcategoria_id": subcategoria_id,
            "categorias_macro": categorias_macro,
            "data_ini": data_ini,
            "data_fim": data_fim,
            "ordering": ordering,
            "categorias_group": categorias_group,
            "total_geral": total_geral,
            "col_data": TX_COL_DATA,
            "col_desc": TX_COL_DESC,
            "col_val": TX_COL_VAL,
            "col_cat": TX_COL_CAT,
            "membros": membros,
            "membro_id": membro_id,
        }
        return render(request, "classificacao/gastos.html", ctx)

    # ---------- Cartão de Crédito ----------
    qs = Lancamento.objects.all()
    qs = _apenas_visiveis_qs(qs)
    qs = _filtrar_periodo_cartao_por_fatura(qs, data_ini, data_fim)

    if categoria_id is not None and categoria_id != "":
        if categoria_id == "0":
            qs = qs.filter(**{f"{LC_COL_CAT}__isnull": True})
        else:
            qs = qs.filter(
                Q(**{f"{LC_COL_CAT}_id": categoria_id}) |
                Q(**{f"{LC_COL_CAT}__categoria_pai_id": categoria_id})
            )

    if subcategoria_id:
        qs = qs.filter(**{f"{LC_COL_CAT}_id": subcategoria_id})

    if membro_id:
        qs = qs.filter(membros__id=membro_id)

    qs = _parse_busca(qs, busca, campos=[LC_COL_DESC])
    qs = _ordenar(qs, default=ordering)

    categorias_group, total_geral = _group_por_categoria(
        qs, "cartao", LC_COL_DATA, LC_COL_DESC, LC_COL_VAL, LC_COL_CAT
    )

    ctx = {
        "fonte": "cartao",
        "busca": busca,
        "categoria_id": categoria_id,
        "subcategoria_id": subcategoria_id,
        "categorias_macro": categorias_macro,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "ordering": ordering,
        "categorias_group": categorias_group,
        "total_geral": total_geral,
        "col_data": LC_COL_DATA,
        "col_desc": LC_COL_DESC,
        "col_val": LC_COL_VAL,
        "col_cat": LC_COL_CAT,
        "membros": membros,
        "membro_id": membro_id,
    }
    return render(request, "classificacao/gastos.html", ctx)


# =========================
# AJAX: atribuir categoria (1 ou muitos)
# =========================
@require_http_methods(["POST"])
def atribuir_categoria_ajax(request: HttpRequest) -> JsonResponse:
    fonte = (request.POST.get("fonte") or "").strip().lower()
    item_id = request.POST.get("item_id")
    item_ids_raw = request.POST.get("item_ids")
    categoria_id = request.POST.get("categoria_id")

    if not fonte:
        return JsonResponse({"ok": False, "erro": "Fonte ausente."}, status=400)
    if not (item_id or item_ids_raw):
        return JsonResponse({"ok": False, "erro": "Informe item_id ou item_ids."}, status=400)

    ids: List[int] = []
    if item_ids_raw:
        try:
            ids = [int(x) for x in item_ids_raw.split(",") if x.strip()]
        except Exception:
            return JsonResponse({"ok": False, "erro": "item_ids inválido."}, status=400)
    elif item_id:
        try:
            ids = [int(item_id)]
        except Exception:
            return JsonResponse({"ok": False, "erro": "item_id inválido."}, status=400)

    # categoria pode ser vazia/0 → remover
    cat_obj = None
    if categoria_id not in (None, "", "0", 0):
        try:
            cat_obj = get_object_or_404(Categoria, pk=int(categoria_id))
        except Exception:
            return JsonResponse({"ok": False, "erro": "categoria_id inválido."}, status=400)

    atualizado = 0
    if fonte == "cc":
        for pk in ids:
            obj = get_object_or_404(Transacao, pk=pk)
            if _has_field(Transacao, "oculta") and getattr(obj, "oculta", False):
                continue
            setattr(obj, TX_COL_CAT, cat_obj)
            obj.save(update_fields=[TX_COL_CAT])
            atualizado += 1
        return JsonResponse({"ok": True, "fonte": "cc", "atualizado": atualizado})

    if fonte == "cartao":
        for pk in ids:
            obj = get_object_or_404(Lancamento, pk=pk)
            if _has_field(Lancamento, "oculta") and getattr(obj, "oculta", False):
                continue
            setattr(obj, LC_COL_CAT, cat_obj)
            obj.save(update_fields=[LC_COL_CAT])
            atualizado += 1
        return JsonResponse({"ok": True, "fonte": "cartao", "atualizado": atualizado})

    return JsonResponse({"ok": False, "erro": "Fonte inválida."}, status=400)


# =========================
# AJAX: atribuir membro (1 ou muitos)
# =========================
@require_http_methods(["POST"])
def atribuir_membro_ajax(request: HttpRequest) -> JsonResponse:
    fonte = (request.POST.get("fonte") or "").strip().lower()
    item_id = request.POST.get("item_id")
    membros_ids_raw = request.POST.getlist("membros_ids")
    membros_ids = [int(x) for x in membros_ids_raw if x.strip()]

    if fonte == "cc":
        ok = atribuir_membro_cc(item_id, membros_ids)
        if ok:
            return JsonResponse({"ok": True, "fonte": "cc"})
        else:
            return JsonResponse({"ok": False, "erro": "Transação não encontrada."}, status=404)
    elif fonte == "cartao":
        ok = atribuir_membro_cartao(item_id, membros_ids)
        if ok:
            return JsonResponse({"ok": True, "fonte": "cartao"})
        else:
            return JsonResponse({"ok": False, "erro": "Lançamento não encontrado."}, status=404)
    return JsonResponse({"ok": False, "erro": "Fonte inválida."}, status=400)


# =========================
# AJAX: subcategorias de uma macro (categoria_pai)
# =========================
@require_http_methods(["GET"])
def carregar_subcategorias_ajax(request: HttpRequest) -> JsonResponse:
    macro_id = request.GET.get("macro_id")
    if not macro_id:
        return JsonResponse({"ok": False, "erro": "macro_id é obrigatório."}, status=400)
    try:
        macro_id_int = int(macro_id)
    except Exception:
        return JsonResponse({"ok": False, "erro": "macro_id inválido."}, status=400)

    qs = Categoria.objects.filter(nivel=2, categoria_pai_id=macro_id_int).order_by("nome")
    itens = [{"id": c.id, "nome": c.nome} for c in qs]
    return JsonResponse({"ok": True, "itens": itens})


# =========================
# AJAX: membros de uma transação
# =========================
@require_http_methods(["GET"])
def membros_transacao_ajax(request: HttpRequest) -> JsonResponse:
    fonte = request.GET.get("fonte")
    item_id = request.GET.get("item_id")
    if fonte == "cc":
        obj = Transacao.objects.get(pk=item_id)
    else:
        obj = Lancamento.objects.get(pk=item_id)
    membros_ids = list(obj.membros.values_list("id", flat=True))
    return JsonResponse({"ok": True, "membros_ids": membros_ids})


# Alias para o urls.py existente
classificacao_gastos = classificacao
