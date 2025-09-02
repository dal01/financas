# core/views/classificacao.py
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_GET

# Ajuste os caminhos se seus apps tiverem nomes diferentes:
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento
from core.models import Categoria


# Helper: marca cada item com .src = 'cc' | 'cartao' quando fonte == 'todas'
def _anotar_src_em_grupos(grupos, fonte):
    if fonte != "todas":
        return grupos
    try:
        from conta_corrente.models import Transacao as _Tx
        from cartao_credito.models import Lancamento as _Lc
    except Exception:
        return grupos
    for macro in grupos or []:
        for sub in macro.get("subs", []):
            for item in sub.get("items", []):
                if getattr(item, "src", None):
                    continue
                if isinstance(item, _Tx):
                    setattr(item, "src", "cc")
                elif isinstance(item, _Lc):
                    setattr(item, "src", "cartao")
                else:
                    setattr(item, "src", "cc")
    return grupos


# ============================================================
# AJAX: carrega subcategorias (filhas) de uma Macro (categoria_pai)
# ============================================================
@require_GET
def carregar_subcategorias_ajax(request):
    """
    GET: ?macro_id=<id>
    Retorna [{"id":..., "nome":...}, ...] para popular o <select> de Subcategoria.
    """
    try:
        macro_id = int(request.GET.get("macro_id"))
    except (TypeError, ValueError):
        return JsonResponse({"items": []})

    subs = (
        Categoria.objects
        .filter(categoria_pai_id=macro_id)
        .order_by("nome")
        .values("id", "nome")
    )
    return JsonResponse({"items": list(subs)})


# ============================================================
# Página: Classificação de Gastos
# ============================================================
@require_http_methods(["GET"])
def classificacao_gastos(request):
    """
    Lista lançamentos agrupados Macro -> Sub, com filtros e totais.

    Pressupostos de campos:
      - Transacao (CC): data, descricao, valor, categoria(FK Categoria), oculta, oculta_manual
      - Lancamento (Cartão): data, descricao, valor, categoria(FK Categoria), oculta, oculta_manual
      - Categoria: nome, categoria_pai(FK self, null=True)
    """
    fonte = request.GET.get("fonte", "todas")          # 'todas' | 'cc' | 'cartao'
    modo = request.GET.get("modo", "ano")              # 'ano' | 'mes'
    ano = int(request.GET.get("ano", "2025"))
    mes = int(request.GET.get("mes", "1"))
    macro_id_sel = request.GET.get("macro_id")         # '', '0' (sem categoria) ou id de Macro
    sub_id_sel = request.GET.get("sub_id") or ""       # '' ou id de Sub
    busca = (request.GET.get("busca") or "").strip()

    # ---------------- Filtros básicos ----------------
    def filtro_periodo(qs, campo_data="data"):
        qs = qs.filter(**{f"{campo_data}__year": ano})
        if modo == "mes":
            qs = qs.filter(**{f"{campo_data}__month": mes})
        return qs

    def filtro_busca(qs):
        if busca:
            qs = qs.filter(descricao__icontains=busca)
        return qs

    def filtro_visibilidade(qs):
        # Oculta tudo que for marcado como oculto (automaticamente ou manualmente)
        return qs.filter(oculta=False, oculta_manual=False)

    def filtro_categoria(qs):
        """
        - macro_id_sel == '0'  => sem categoria
        - sub_id_sel != ''     => filtra pela sub diretamente
        - macro_id_sel != ''   => filtra por categoria__categoria_pai_id = macro
        """
        if macro_id_sel == "0":
            return qs.filter(categoria__isnull=True)
        if sub_id_sel:
            return qs.filter(categoria_id=sub_id_sel)
        if macro_id_sel and macro_id_sel != "":
            return qs.filter(categoria__categoria_pai_id=macro_id_sel)
        return qs

    # ---------------- Monta QuerySets ----------------
    qs_cc = Transacao.objects.all()
    qs_cartao = Lancamento.objects.all()

    # visibilidade primeiro
    qs_cc = filtro_visibilidade(qs_cc)
    qs_cartao = filtro_visibilidade(qs_cartao)

    qs_cc = filtro_periodo(qs_cc, campo_data="data")
    qs_cartao = filtro_periodo(qs_cartao, campo_data="data")

    qs_cc = filtro_busca(qs_cc)
    qs_cartao = filtro_busca(qs_cartao)

    qs_cc = filtro_categoria(qs_cc)
    qs_cartao = filtro_categoria(qs_cartao)

    # Evita N+1 na árvore de categoria
    items_cc = []
    items_cartao = []
    if fonte in ("todas", "cc"):
        items_cc = list(qs_cc.select_related("categoria", "categoria__categoria_pai"))
    if fonte in ("todas", "cartao"):
        items_cartao = list(qs_cartao.select_related("categoria", "categoria__categoria_pai"))

    # ---------------- Agrupamento Macro -> Sub ----------------
    def obter_macro_sub(item):
        cat = getattr(item, "categoria", None)
        if cat is None:
            return "Sem categoria", "Sem categoria", None, None
        pai = getattr(cat, "categoria_pai", None)
        if pai is None:
            return (cat.nome or "Sem categoria"), "Sem categoria", cat, None
        return (pai.nome or "Sem categoria", cat.nome or "Sem categoria", pai, cat)

    grupos_map: dict[str, dict] = {}

    def add_item(item, origem: str):
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

        setattr(item, "src", origem)
        s["items"].append(item)

    for it in items_cc:
        add_item(it, "cc")
    for it in items_cartao:
        add_item(it, "cartao")

    def ordem(n):
        return (n == "Sem categoria", (n or "").lower())

    grupos = []
    for macro_nome in sorted(grupos_map.keys(), key=ordem):
        macro_info = grupos_map[macro_nome]
        subs_list = []
        for sub_nome in sorted(macro_info["subs_map"].keys(), key=ordem):
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

    # Anota origem (garantia) e prepara contexto
    grupos = _anotar_src_em_grupos(grupos, fonte)

    anos_disponiveis = [ano - 1, ano, ano + 1]
    meses = [(i, f"{i:02d}") for i in range(1, 13)]
    periodo_label = f"{'Ano' if modo=='ano' else 'Mês'} de {ano}" + ("" if modo == "ano" else f" / {mes:02d}")
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


# ============================================================
# AJAX: Atribuir categoria (robusto, sem colisão)
# ============================================================
@require_http_methods(["POST"])
def atribuir_categoria_ajax(request):
    """
    Espera:
      - ids_cc: '1,2,3'     (opcional)
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
        updated_cc = Transacao.objects.filter(id__in=ids_cc).update(categoria=categoria) if ids_cc else 0
        updated_lc = Lancamento.objects.filter(id__in=ids_lc).update(categoria=categoria) if ids_lc else 0

    return JsonResponse({"ok": True, "cc": updated_cc, "cartao": updated_lc})
