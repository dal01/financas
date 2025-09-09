# relatorios/views/gastos_categorias.py
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Iterable
from datetime import date, datetime

from django.db.models import DateTimeField
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.models import Categoria, Membro
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
    "Cartão de Crédito",   # <- ignorar também essa macro
]
_IGNORAR_SET = {n.strip().lower() for n in IGNORAR_CATEGORIAS if n}


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


def _with_membros(qs):
    """
    Faz prefetch de 'membros' se o modelo tiver esse M2M.
    Evita N+1 ao chamar .count() dentro do loop.
    """
    try:
        if _has_field(qs.model, "membros"):
            return qs.prefetch_related("membros")
    except Exception:
        pass
    return qs


def _filtrar_periodo(qs, data_ini: str, data_fim: str, campo_data: str):
    """
    data_ini/data_fim no formato 'YYYY-MM-DD'.
    Suporta campos relacionados (ex.: 'fatura__competencia').
    Usa '__date' somente quando sabemos que é DateTimeField direto do modelo raiz;
    em campos relacionados, aplicamos direto (Django resolve corretamente para DateField).
    """
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


def _filtrar_por_membro(qs, membro_id: Optional[str]):
    """
    Aplica filtro por membro se informado, tentando em ordem:
    - M2M 'membros'
    - FK 'membro'
    - Caminho típico de lançamento: fatura__cartao__membro
    Silenciosamente ignora caso nada se aplique.
    """
    if not membro_id:
        return qs

    try:
        mid = int(membro_id)
    except Exception:
        return qs

    # 1) M2M 'membros'
    if _has_field(qs.model, "membros"):
        try:
            return qs.filter(membros__id=mid)
        except Exception:
            pass

    # 2) FK 'membro'
    if _has_field(qs.model, "membro"):
        try:
            return qs.filter(membro_id=mid)
        except Exception:
            pass

    # 3) Lançamento -> Fatura -> Cartão -> Membro (titular do cartão)
    try:
        return qs.filter(fatura__cartao__membro_id=mid)
    except Exception:
        return qs


def _count_membros(obj) -> int:
    """
    Conta quantos membros estão ligados ao objeto via M2M 'membros'.
    Retorna 0 se não existir o campo ou ocorrer erro.
    """
    if hasattr(obj, "membros"):
        try:
            return obj.membros.count()
        except Exception:
            return 0
    return 0


def _valor_gasto_transacao(obj) -> Decimal:
    """
    Calcula o gasto normalizado de uma Transacao.
    - Conta-corrente: valores negativos = despesa (→ positivo), positivos (receita) = 0.
    - Divide pelo número de membros (M2M 'membros'), quando houver 1+ membros.
    """
    v = Decimal(getattr(obj, TX_COL_VAL, 0) or 0)
    gasto = -v if v < 0 else Decimal("0")

    qtd = _count_membros(obj)
    if qtd > 0:
        gasto = gasto / qtd
    return gasto


def _valor_gasto_lancamento(obj) -> Decimal:
    """
    Calcula o gasto normalizado de um Lancamento.
    - Cartão: positivos = despesa; negativos = estorno (abate total).
    - Divide pelo número de membros (M2M 'membros'), quando houver 1+ membros.
    """
    v = Decimal(getattr(obj, LC_COL_VAL, 0) or 0)
    gasto = Decimal(v)

    qtd = _count_membros(obj)
    if qtd > 0:
        gasto = gasto / qtd
    return gasto


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
        # Valor efetivo considerando normalização + divisão por membros
        if fonte == "cc":
            gasto = _valor_gasto_transacao(obj)
        else:
            gasto = _valor_gasto_lancamento(obj)

        # Categoria -> macro/sub
        c: Optional[Categoria] = getattr(obj, col_cat, None)
        macro_id, macro_nome, sub_id, sub_nome = _macro_sub_de(c)

        # Ignorar categorias da lista
        if macro_nome and macro_nome.strip().lower() in _IGNORAR_SET:
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
# VIEW (usa data da fatura para cartão) + filtro por membro + divisão por membros
# =========================
def gastos_categorias(request: HttpRequest) -> HttpResponse:
    """
    Relatório consolidado de gastos por categoria (macro e sub), somando:
      - Transação (Conta Corrente) — filtro por Transacao.data
      - Lançamento (Cartão de Crédito) — filtro por data da Fatura (LC_COL_DATA)

    Filtros:
      - Período: data_ini / data_fim (YYYY-MM-DD)
      - Membro: membro_id (em branco = todos)

    Regras:
      - Conta-corrente: negativos viram positivos; positivos (receitas) não somam.
      - Cartão: positivos somam; negativos (estornos) abatem.
      - Se houver M2M 'membros', o valor é dividido igualmente pela quantidade.
    """
    # Período padrão
    hoje = date.today()
    data_ini_default = date(hoje.year, 1, 1).strftime("%Y-%m-%d")
    data_fim_default = hoje.strftime("%Y-%m-%d")

    data_ini = (request.GET.get("data_ini") or data_ini_default).strip()
    data_fim = (request.GET.get("data_fim") or data_fim_default).strip()

    membro_id = (request.GET.get("membro_id") or "").strip()  # string
    membro_nome = None
    if membro_id:
        try:
            membro_obj = Membro.objects.get(id=int(membro_id))
            membro_nome = membro_obj.nome
        except Exception:
            membro_id = ""  # invalida se não achou

    # Conta Corrente (usa Transacao.data)
    qs_tx = Transacao.objects.select_related("categoria")
    qs_tx = _with_membros(qs_tx)                      # prefetch membros (se houver)
    qs_tx = _apenas_visiveis_qs(qs_tx)
    qs_tx = _filtrar_periodo(qs_tx, data_ini, data_fim, TX_COL_DATA)
    qs_tx = _filtrar_por_membro(qs_tx, membro_id)

    # Cartão (usa data da Fatura definida em LC_COL_DATA)
    qs_lc = Lancamento.objects.select_related("fatura", "categoria", "fatura__cartao")
    qs_lc = _with_membros(qs_lc)                      # prefetch membros (se houver)
    qs_lc = _apenas_visiveis_qs(qs_lc)
    qs_lc = _filtrar_periodo(qs_lc, data_ini, data_fim, LC_COL_DATA)
    qs_lc = _filtrar_por_membro(qs_lc, membro_id)

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
        "membros": Membro.objects.order_by("nome"),
        "membro_id": membro_id,
        "membro_nome": membro_nome,
    }
    return render(request, "relatorios/gastos_categorias.html", ctx)


# Compat com import antigo
gastos_por_categoria = gastos_categorias
