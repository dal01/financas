from __future__ import annotations
from datetime import date

from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.db import transaction, models
from django.http import HttpRequest, HttpResponseBadRequest

from cartao_credito.models import Lancamento
from core.models import Membro, Categoria

from ..services.parcelados import agrupar_parcelados  # já retorna debug quando pedido

def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None

def _bool_param(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "on", "yes", "y", "sim"}

@require_http_methods(["GET"])
def parcelados_list(request: HttpRequest):
    hoje = date.today()
    ini_default = date(hoje.year, 1, 1)
    fim_default = hoje

    d_ini = _parse_date(request.GET.get("data_ini")) or ini_default
    d_fim = _parse_date(request.GET.get("data_fim")) or fim_default
    busca = (request.GET.get("busca") or "").strip()
    want_debug = _bool_param(request.GET.get("debug"))

    base_qs = Lancamento.objects.filter(
        data__gte=d_ini, data__lte=d_fim,
        oculta=False, oculta_manual=False,
    )
    if busca:
        base_qs = base_qs.filter(models.Q(descricao__icontains=busca))

    if want_debug:
        grupos, debug_data = agrupar_parcelados(base_qs, return_debug=True)
    else:
        grupos = agrupar_parcelados(base_qs)
        debug_data = None

    ids_por_grupo = {g.group_id: g.lancamento_ids for g in grupos}
    objs_por_grupo: dict[str, list[Lancamento]] = {}
    if ids_por_grupo:
        todos_ids = [lid for ids in ids_por_grupo.values() for lid in ids]
        objetos = (
            Lancamento.objects
            .filter(id__in=todos_ids)
            .select_related("fatura__cartao", "categoria")
            .prefetch_related("membros")
        )
        obj_map = {o.id: o for o in objetos}
        for gid, ids in ids_por_grupo.items():
            objs_por_grupo[gid] = [obj_map[i] for i in ids if i in obj_map]

    grupos_ctx = [(g, objs_por_grupo.get(g.group_id, [])) for g in grupos]

    membros = list(Membro.objects.all().order_by("nome"))
    categorias = list(Categoria.objects.all().order_by("nivel", "categoria_pai__nome", "nome"))

    ctx = dict(
        data_ini=d_ini,
        data_fim=d_fim,
        busca=busca,
        grupos_ctx=grupos_ctx,
        membros=membros,
        categorias=categorias,
        debug_data=debug_data,
        want_debug=want_debug,
    )
    return render(request, "cartao_credito/parcelados.html", ctx)

@require_http_methods(["POST"])
@transaction.atomic
def parcelados_acao(request: HttpRequest):
    action = request.POST.get("action")
    group_id = request.POST.get("group_id")
    data_ini = request.POST.get("data_ini")
    data_fim = request.POST.get("data_fim")
    busca = request.POST.get("busca", "")
    want_debug = _bool_param(request.POST.get("debug"))

    d_ini = _parse_date(data_ini)
    d_fim = _parse_date(data_fim)
    if not (d_ini and d_fim):
        return HttpResponseBadRequest("Período inválido.")

    qs = Lancamento.objects.filter(
        data__gte=d_ini, data__lte=d_fim,
        oculta=False, oculta_manual=False,
    )
    if busca:
        qs = qs.filter(models.Q(descricao__icontains=busca))

    grupos = agrupar_parcelados(qs)
    alvo = next((g for g in grupos if g.group_id == group_id), None)
    if not alvo:
        return HttpResponseBadRequest("Grupo não encontrado para o filtro atual.")

    lanc_ids = alvo.lancamento_ids
    lcts = list(Lancamento.objects.filter(id__in=lanc_ids).select_for_update())

    if action == "set_membros":
        membros_ids = [int(x) for x in request.POST.getlist("membros_ids")]
        membros = list(Membro.objects.filter(id__in=membros_ids))
        for l in lcts:
            l.membros.set(membros)

    elif action == "set_categoria":
        cat_id = request.POST.get("categoria_id")
        if not cat_id:
            return HttpResponseBadRequest("Categoria não informada.")
        try:
            cat = Categoria.objects.get(id=int(cat_id))
        except Categoria.DoesNotExist:
            return HttpResponseBadRequest("Categoria inválida.")
        for l in lcts:
            l.categoria = cat
            l.save(update_fields=["categoria"])
    else:
        return HttpResponseBadRequest("Ação não suportada.")

    debug_qs = "&debug=1" if want_debug else ""
    return redirect(
        f"{request.META.get('HTTP_REFERER', '')}".split("?")[0]
        + f"?data_ini={d_ini}&data_fim={d_fim}&busca={busca}{debug_qs}"
    )
