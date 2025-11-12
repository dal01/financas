# relatorios/views/gastos_categorias.py
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.models import Membro
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

from conta_corrente.utils.helpers import (
    transacoes_visiveis,
    transacoes_periodo,
    transacoes_membro,
)
from cartao_credito.utils.helpers import (
    lancamentos_visiveis,
    lancamentos_periodo,
    lancamentos_membro,
)

from relatorios.utils_gastos import (
    _has_field, _is_datetime_field,
    _count_membros, _valor_gasto_transacao, _valor_gasto_lancamento,
    _macro_sub_de, _agrupar_por_categoria
)

from core.utils.tempo import periodo_padrao, valida_data

TX_COL_VAL = "valor"
TX_COL_CAT = "categoria"
LC_COL_VAL = "valor"
LC_COL_CAT = "categoria"
LC_COL_DATA = "fatura__competencia"

IGNORAR_CATEGORIAS = [
    "Pagamentos de cartão",
    "Cartão de Crédito",
]
_IGNORAR_SET = {n.strip().lower() for n in IGNORAR_CATEGORIAS if n}

def gastos_categorias(request: HttpRequest) -> HttpResponse:
    """
    Relatório consolidado de gastos por categoria (macro e sub), somando:
      - Transação (Conta Corrente) — filtro por Transacao.data
      - Lançamento (Cartão de Crédito) — filtro por data da Fatura (LC_COL_DATA)
    """
    # Período padrão
    data_ini_default, data_fim_default = periodo_padrao()
    data_ini = (request.GET.get("data_ini") or data_ini_default).strip()
    data_fim = (request.GET.get("data_fim") or data_fim_default).strip()

    membro_id = (request.GET.get("membro_id") or "").strip()
    membro_nome = None
    membros = [int(membro_id)] if membro_id else None
    if membro_id:
        try:
            membro_obj = Membro.objects.get(id=int(membro_id))
            membro_nome = membro_obj.nome
        except Exception:
            membro_id = ""
            membros = None

    # Conta Corrente
    qs_tx = Transacao.objects.select_related("categoria").prefetch_related("membros")
    qs_tx = transacoes_visiveis(qs_tx)
    qs_tx = transacoes_periodo(qs_tx, data_ini, data_fim)
    qs_tx = transacoes_membro(qs_tx, membros)

    # Cartão de Crédito
    qs_lc = Lancamento.objects.select_related("fatura", "categoria", "fatura__cartao").prefetch_related("membros")
    qs_lc = lancamentos_visiveis(qs_lc)
    qs_lc = lancamentos_periodo(qs_lc, data_ini, data_fim)
    qs_lc = lancamentos_membro(qs_lc, membros)

    # Corrige o rateio: só divide se filtrando por membro específico
    ratear = membros is not None  # membros=None significa "todos", não rateia

    macros_tx, _ = _agrupar_por_categoria(qs_tx, "cc", TX_COL_VAL, TX_COL_CAT, ratear=ratear)
    macros_lc, _ = _agrupar_por_categoria(qs_lc, "cartao", LC_COL_VAL, LC_COL_CAT, ratear=ratear)

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
            # Converte Decimal para float e ordena por valor (maior primeiro)
            subs = [{"id": s["id"], "nome": s["nome"], "total": float(s["total"])} for s in subs]
            subs.sort(key=lambda x: -x["total"])  # Ordena por valor decrescente
            
            out.append({
                "id": m["id"], 
                "nome": m["nome"], 
                "total": float(m["total"]), 
                "subcats": subs
            })
        
        # Ordena categorias por valor (maior primeiro)
        out.sort(key=lambda x: -x["total"])

        return out, float(total_geral)

    categorias, total_geral = _merge(macros_tx, macros_lc)
    
    # Debug: imprime no console do Django
    print(f"DEBUG - Total de categorias: {len(categorias)}")
    for i, cat in enumerate(categorias[:3]):
        print(f"DEBUG - Categoria {i+1}: {cat['nome']} = R$ {cat['total']}")

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

gastos_por_categoria = gastos_categorias