# relatorios/views/gastos_categorias.py
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Iterable
from datetime import date, datetime

from django.db.models import Q, DateTimeField
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.models import Categoria
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

# =========================
# Configuração de campos
# =========================
# Conta Corrente
TX_COL_DATA = "data"
TX_COL_VAL = "valor"
TX_COL_DESC = "descricao"
TX_COL_CAT = "categoria"

# Cartão de Crédito
# >>> AQUI definimos "data da fatura" que será usada no filtro do período:
# Use UMA das três linhas abaixo (deixe as outras comentadas):
LC_COL_DATA = "fatura__competencia"       # mês de competência (1º dia do mês)  << recomendado para relatórios mensais
# LC_COL_DATA = "fatura__vencimento_em"   # data de vencimento da fatura
# LC_COL_DATA = "fatura__fechado_em"      # data de fechamento da fatura

LC_COL_VAL = "valor"
LC_COL_DESC = "descricao"
LC_COL_CAT = "categoria"

IGNORAR_CATEGORIAS = [
    "Pagamentos de cartão",
    "Cartão de Crédito",   # <- nova categoria a ser ignorada
]



# =========================
# Helpers
# =========================
def _has_field(model, field_name: str) -> bool:
    try:
        return any(f.name == field_name for f in model._meta.get_fields())
    except Exception:
        return False


def _is_datetime_field(model, field_name: str) -> bool:
    try:
        f = model._meta.get_field(field_name)
        return isinstance(f, DateTimeField)
    except Exception:
        # Campo relacionado (ex.: fatura__competencia) cai aqui; tratamos como DateField
        return False


def _apenas_visiveis_qs(qs):
    if _has_field(qs.model, "oculta"):
        qs = qs.exclude(oculta=True)
    return qs


def _filtrar_periodo(qs, data_ini: str, data_fim: str, campo_data: str):
    """
    data_ini/data_fim no formato 'YYYY-MM-DD'.
    Suporta campos relacionados (ex.: 'fatura__competencia').
    Usa '__date' somente quando sabemos que é DateTimeField direto do modelo raiz;
    em campos relacionados, aplicamos direto (Django resolve corretamente para DateField).
    """
    # Tenta detectar DateTimeField só quando o campo é direto do modelo
    is_direct_field = "__" not in campo_data
    is_dt = _is_datetime_field(qs.model, campo_data) if is_direct_field else False
    prefix = f"{campo_data}__date" if is_dt else campo_data

    def _valid(s: str) -> bool:
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return True
        except Exception:
            return False

    if data_ini and _valid(data_ini):
        qs = qs.filter(**{f"{prefix}__gte": data_ini})
    if data_fim and _valid(data_fim):
        qs = qs.filter(**{f"{prefix}__lte": data_fim})
    return qs


def _valor_gasto_transacao(v: Decimal) -> Decimal:
    # CC: negativos = despesa (→ positivo); positivos (receita) = 0
    v = Decimal(v or 0)
    return -v if v < 0 else Decimal("0")


def _valor_gasto_lancamento(v: Decimal) -> Decimal:
    # Cartão: positivos = despesa; negativos = estorno (abate)
    return Decimal(v or 0)


def _macro_sub_de(c: Optional[Categoria]) -> Tuple[int, str, int, str]:
    """
    Retorna (macro_id, macro_nome, sub_id, sub_nome) dado uma Categoria (ou None).
    """
    if c is None:
        return (0, "Sem categoria", 0, "Sem subcategoria")
    if getattr(c, "nivel", None) == 1:
        return (c.id, c.nome, 0, "Sem subcategoria")
    pai = getattr(c, "categoria_pai", None)
    if pai:
        return (pai.id, pai.nome, c.id, c.nome)
    # Sem pai conhecido (degrada para "Sem categoria")
    return (0, "Sem categoria", c.id or 0, c.nome or "Sem subcategoria")


def _agrupar_por_categoria(
    itens: Iterable,
    fonte: str,
    col_val: str,
    col_cat: str,
) -> Tuple[List[Dict], Decimal]:
    """
    Retorna:
    [
      {
        "id": macro_id, "nome": macro_nome, "total": Decimal,
        "subcats": [
           {"id": sub_id, "nome": sub_nome, "total": Decimal}
        ]
      },
      ...
    ], total_geral
    """
    total_geral = Decimal("0")
    macros: Dict[int, Dict] = {}

    for obj in itens:
        valor = getattr(obj, col_val, Decimal("0")) or Decimal("0")
        gasto = _valor_gasto_transacao(valor) if fonte == "cc" else _valor_gasto_lancamento(valor)

        c: Optional[Categoria] = getattr(obj, col_cat, None)
        macro_id, macro_nome, sub_id, sub_nome = _macro_sub_de(c)

        # Ignorar categorias da lista
        if macro_nome and macro_nome.strip().lower() in [n.lower() for n in IGNORAR_CATEGORIAS]:
            continue


        m = macros.setdefault(macro_id, {"id": macro_id, "nome": macro_nome, "total": Decimal("0"), "subs": {}})
        s = m["subs"].setdefault(sub_id, {"id": sub_id, "nome": sub_nome, "total": Decimal("0")})

        s["total"] += gasto
        m["total"] += gasto
        total_geral += gasto

    # Ordenação por total desc e nome
    out: List[Dict] = []
    for m in macros.values():
        subs = list(m["subs"].values())
        subs.sort(key=lambda x: (x["total"], x["nome"]), reverse=True)
        out.append({"id": m["id"], "nome": m["nome"], "total": m["total"], "subcats": subs})
    out.sort(key=lambda x: (x["total"], x["nome"]), reverse=True)

    return out, total_geral


# =========================
# VIEW (usa data da fatura para cartão)
# =========================
def gastos_categorias(request: HttpRequest) -> HttpResponse:
    """
    Relatório consolidado de gastos por categoria (macro e sub), somando:
      - Transação (Conta Corrente) — filtro por Transacao.data
      - Lançamento (Cartão de Crédito) — filtro por data da Fatura (LC_COL_DATA)

    Período: data_ini / data_fim (YYYY-MM-DD)
    Padrão: 1º jan do ano corrente até hoje.
    """
    # Período padrão
    hoje = date.today()
    data_ini_default = date(hoje.year, 1, 1).strftime("%Y-%m-%d")
    data_fim_default = hoje.strftime("%Y-%m-%d")

    data_ini = (request.GET.get("data_ini") or data_ini_default).strip()
    data_fim = (request.GET.get("data_fim") or data_fim_default).strip()

    # Conta Corrente (usa Transacao.data)
    qs_tx = _apenas_visiveis_qs(Transacao.objects.all())
    qs_tx = _filtrar_periodo(qs_tx, data_ini, data_fim, TX_COL_DATA)

    # Cartão (usa data da Fatura definida em LC_COL_DATA)
    qs_lc = _apenas_visiveis_qs(Lancamento.objects.select_related("fatura", "categoria"))
    qs_lc = _filtrar_periodo(qs_lc, data_ini, data_fim, LC_COL_DATA)

    # Agrupar separadamente por conta das regras de normalização
    macros_tx, _ = _agrupar_por_categoria(qs_tx, "cc", TX_COL_VAL, TX_COL_CAT)
    macros_lc, _ = _agrupar_por_categoria(qs_lc, "cartao", LC_COL_VAL, LC_COL_CAT)

    # Merge das duas fontes
    def _merge(macros_a: List[Dict], macros_b: List[Dict]) -> Tuple[List[Dict], Decimal]:
        idx: Dict[int, Dict] = {}
        total_geral = Decimal("0")

        def acc(macro_list: List[Dict]):
            nonlocal total_geral
            for m in macro_list:
                mm = idx.setdefault(m["id"], {"id": m["id"], "nome": m["nome"], "total": Decimal("0"), "subs": {}})
                mm["total"] += m["total"]
                total_geral += m["total"]
                for s in m["subcats"]:
                    ss = mm["subs"].setdefault(s["id"], {"id": s["id"], "nome": s["nome"], "total": Decimal("0")})
                    ss["total"] += s["total"]

        acc(macros_tx)
        acc(macros_lc)

        out: List[Dict] = []
        for m in idx.values():
            subs = list(m["subs"].values())
            subs.sort(key=lambda x: (x["total"], x["nome"]), reverse=True)
            out.append({"id": m["id"], "nome": m["nome"], "total": m["total"], "subcats": subs})
        out.sort(key=lambda x: (x["total"], x["nome"]), reverse=True)
        return out, total_geral

    categorias, total_geral = _merge(macros_tx, macros_lc)

    ctx = {
        "data_ini": data_ini,
        "data_fim": data_fim,
        "categorias": categorias,
        "total_geral": total_geral,
    }
    return render(request, "relatorios/gastos_categorias.html", ctx)


# Compat com import antigo
gastos_por_categoria = gastos_categorias
