# core/views/classificacao.py
from __future__ import annotations

from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.db import transaction

# Ajuste os caminhos para seus apps/modelos:
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento
from core.models import Categoria

from django.views.decorators.http import require_GET

@require_GET
def carregar_subcategorias_ajax(request):
    """
    Retorna as subcategorias de uma categoria macro (pai).
    GET: ?macro_id=<id>
    """
    try:
        macro_id = int(request.GET.get("macro_id"))
    except (TypeError, ValueError):
        return JsonResponse({"items": []})

    # campo correto é categoria_pai
    subs = Categoria.objects.filter(categoria_pai_id=macro_id).order_by("nome").values("id", "nome")
    return JsonResponse({"items": list(subs)})



@require_http_methods(["GET"])
def classificacao_gastos(request):
    """
    Lista lançamentos agrupados Macro -> Sub, com filtros e totais.
    Campos assumidos:
      - Transacao: data, descricao, valor, categoria(FK Categoria)
      - Lancamento: data, descricao, valor, categoria(FK Categoria)
      - Categoria: nome, categoria_pai (FK self, pode ser null)
    """
    from decimal import Decimal

    fonte = request.GET.get("fonte", "todas")             # 'todas' | 'cc' | 'cartao'
    modo = request.GET.get("modo", "ano")                  # 'ano' | 'mes'
    ano = int(request.GET.get("ano", "2025"))
    mes = int(request.GET.get("mes", "1"))
    macro_id_sel = request.GET.get("macro_id")             # '', '0' (sem categoria), ou id de macro
    sub_id_sel = request.GET.get("sub_id") or ""           # '' ou id de sub
    busca = (request.GET.get("busca") or "").strip()

    # ===== Filtro de período =====
    def filtro_periodo(qs, campo_data="data"):
        qs = qs.filter(**{f"{campo_data}__year": ano})
        if modo == "mes":
            qs = qs.filter(**{f"{campo_data}__month": mes})
        return qs

    # ===== Filtro de busca =====
    def filtro_busca(qs):
        if busca:
            qs = qs.filter(descricao__icontains=busca)
        return qs

    # ===== Filtro Macro/Sub =====
    # - macro_id_sel == '0'  => sem categoria
    # - sub_id_sel != ''     => filtra pela sub diretamente
    # - macro_id_sel != ''   => filtra por "categoria__categoria_pai_id = macro"
    def filtro_categoria(qs):
        if macro_id_sel == "0":
            return qs.filter(categoria__isnull=True)
        if sub_id_sel:
            return qs.filter(categoria_id=sub_id_sel)
        if macro_id_sel and macro_id_sel != "":
            return qs.filter(categoria__categoria_pai_id=macro_id_sel)
        return qs

    # ===== QuerySets por origem =====
    qs_cc = Transacao.objects.all()
    qs_cartao = Lancamento.objects.all()

    qs_cc = filtro_periodo(qs_cc, campo_data="data")
    qs_cartao = filtro_periodo(qs_cartao, campo_data="data")

    qs_cc = filtro_busca(qs_cc)
    qs_cartao = filtro_busca(qs_cartao)

    qs_cc = filtro_categoria(qs_cc)
    qs_cartao = filtro_categoria(qs_cartao)

    # Evita N+1: note o uso de categoria__categoria_pai
    if fonte in ("todas", "cc"):
        items_cc = list(qs_cc.select_related("categoria", "categoria__categoria_pai"))
    else:
        items_cc = []
    if fonte in ("todas", "cartao"):
        items_cartao = list(qs_cartao.select_related("categoria", "categoria__categoria_pai"))
    else:
        items_cartao = []

    # ===== Helpers =====
    def obter_macro_sub(item):
        """
        Retorna (macro_nome, sub_nome, macro_obj, sub_obj) com base em Categoria.categoria_pai.
        """
        cat = getattr(item, "categoria", None)
        if cat is None:
            return "Sem categoria", "Sem categoria", None, None

        pai = getattr(cat, "categoria_pai", None)
        if pai is None:
            # categoria de topo -> macro = cat, sub = "Sem categoria"
            return (cat.nome or "Sem categoria"), "Sem categoria", cat, None
        # categoria com pai -> macro = pai, sub = cat
        return (pai.nome or "Sem categoria", cat.nome or "Sem categoria", pai, cat)

    from collections import defaultdict
    grupos_map = {}

    def add_item(item, origem):
        macro_nome, sub_nome, _macro_obj, _sub_obj = obter_macro_sub(item)

        valor = getattr(item, "valor", Decimal("0"))
        soma = abs(Decimal(valor)) if origem == "cc" else Decimal(valor)

        if macro_nome not in grupos_map:
            grupos_map[macro_nome] = {"total_macro": Decimal("0"), "subs_map": {}}
        g = grupos_map[macro_nome]
        g["total_macro"] += soma

        if sub_nome not in g["subs_map"]:
            g["subs_map"][sub_nome] = {"total_sub": Decimal("0"), "items": []}
        s = g["subs_map"][sub_nome]
        s["total_sub"] += soma

        # para o template (data-origin)
        setattr(item, "src", origem)
        s["items"].append(item)

    for it in items_cc:
        add_item(it, "cc")
    for it in items_cartao:
        add_item(it, "cartao")

    def ordem_nome(n):
        # "Sem categoria" por último
        return (n == "Sem categoria", (n or "").lower())

    grupos = []
    for macro_nome in sorted(grupos_map.keys(), key=ordem_nome):
        macro_info = grupos_map[macro_nome]
        subs_list = []
        for sub_nome in sorted(macro_info["subs_map"].keys(), key=ordem_nome):
            s = macro_info["subs_map"][sub_nome]
            subs_list.append({
                "sub_nome": sub_nome,
                "total_sub": s["total_sub"],
                "items": s["items"],
            })
        grupos.append({
            "macro_nome": macro_nome,
            "total_macro": macro_info["total_macro"],
            "subs": subs_list,
        })

    # Auxiliares do template
    anos_disponiveis = [ano - 1, ano, ano + 1]
    meses = [(i, f"{i:02d}") for i in range(1, 13)]
    periodo_label = f"{'Ano' if modo=='ano' else 'Mês'} de {ano}" + ("" if modo == "ano" else f" / {mes:02d}")
    # Macros = categorias de topo (categoria_pai is null)
    macros = Categoria.objects.filter(categoria_pai__isnull=True).order_by("nome")

    ctx = {
        "title": "Classificação de Gastos",
        "fonte": fonte,
        "modo": modo,
        "ano": ano,
        "mes": mes,
        "macro_id_sel": 0 if macro_id_sel == "0" else macro_id_sel,
        "sub_id_sel": sub_id_sel,
        "busca": busca,
        "periodo_label": periodo_label,
        "anos_disponiveis": anos_disponiveis,
        "meses": meses,
        "macros": macros,
        "grupos": grupos,
    }
    return render(request, "classificacao/gastos.html", ctx)




@require_http_methods(["POST"])
def atribuir_categoria_ajax(request):
    """
    Espera:
      - ids_cc: '1,2,3' (opcional)
      - ids_cartao: '4,5,6' (opcional)
      - categoria_id: '' para limpar, ou um ID válido
    """
    categoria_id = (request.POST.get("categoria_id") or "").strip()
    ids_cc_raw = (request.POST.get("ids_cc") or "").strip()
    ids_cartao_raw = (request.POST.get("ids_cartao") or "").strip()

    if not ids_cc_raw and not ids_cartao_raw:
        return HttpResponseBadRequest("Nenhum ID informado (ids_cc/ids_cartao).")

    categoria = None
    if categoria_id:
        try:
            categoria = Categoria.objects.get(pk=categoria_id)
        except Categoria.DoesNotExist:
            return HttpResponseBadRequest("Categoria inválida.")

    try:
        ids_cc = [int(x) for x in ids_cc_raw.split(",") if x] if ids_cc_raw else []
        ids_lc = [int(x) for x in ids_cartao_raw.split(",") if x] if ids_cartao_raw else []
    except ValueError:
        return HttpResponseBadRequest("IDs inválidos.")

    with transaction.atomic():
        updated_cc = updated_lc = 0
        if ids_cc:
            updated_cc = Transacao.objects.filter(id__in=ids_cc).update(categoria=categoria)
        if ids_lc:
            updated_lc = Lancamento.objects.filter(id__in=ids_lc).update(categoria=categoria)

    return JsonResponse({"ok": True, "cc": updated_cc, "cartao": updated_lc})
