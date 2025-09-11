# relatorios/views/gastos_categorias.py
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.models import Membro
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

from relatorios.utils_gastos import (
    _has_field, _is_datetime_field, _apenas_visiveis_qs, _with_membros,
    _filtrar_periodo, _filtrar_por_membro, _count_membros,
    _valor_gasto_transacao, _valor_gasto_lancamento,
    _macro_sub_de, _agrupar_por_categoria
)

from core.utils.tempo import periodo_padrao, valida_data

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
    data_ini_default, data_fim_default = periodo_padrao()
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
