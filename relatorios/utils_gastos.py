# relatorios/views/gastos_categorias.py
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Iterable
from datetime import datetime

from django.db.models import DateTimeField

from core.models import Categoria

# =========================
# Configuração de categorias ignoradas
# =========================
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
        return False


def _apenas_visiveis_qs(qs):
    if _has_field(qs.model, "oculta"):
        qs = qs.filter(oculta=False)
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
        membro_id_int = int(membro_id)
    except Exception:
        return qs

    # 1) M2M 'membros'
    if _has_field(qs.model, "membros"):
        return qs.filter(membros__id=membro_id_int)
    # 2) FK 'membro'
    if _has_field(qs.model, "membro"):
        return qs.filter(membro__id=membro_id_int)
    # 3) Caminho típico de lançamento: fatura__cartao__membro
    if _has_field(qs.model, "fatura"):
        return qs.filter(fatura__cartao__membro__id=membro_id_int)
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


def _valor_gasto_transacao(obj, col_val: str, ratear: bool = True) -> Decimal:
    """
    Calcula o gasto normalizado de uma Transacao.
    - Conta-corrente: valores negativos = despesa (→ positivo), positivos (receita) = 0.
    - Divide pelo número de membros (M2M 'membros'), quando houver 1+ membros.
    """
    v = Decimal(getattr(obj, col_val, 0) or 0)
    # Negativos viram positivos (gasto); positivos (receita) não somam
    if v < 0:
        qtd = _count_membros(obj)
        gasto = abs(v)
        if ratear and qtd > 0:
            gasto = gasto / qtd
        return gasto
    return Decimal("0")


def _valor_gasto_lancamento(obj, col_val: str, ratear: bool = True) -> Decimal:
    """
    Calcula o gasto normalizado de um Lancamento.
    - Cartão: positivos = despesa; negativos = estorno (abate total).
    - Divide pelo número de membros (M2M 'membros'), quando houver 1+ membros.
    """
    v = Decimal(getattr(obj, col_val, 0) or 0)
    gasto = Decimal(v)

    qtd = _count_membros(obj)
    if ratear and qtd > 0:
        gasto = gasto / qtd
    return gasto


def _macro_sub_de(c: Optional[Categoria]) -> Tuple[int, str, int, str]:
    """
    Retorna (macro_id, macro_nome, sub_id, sub_nome) dado uma Categoria (ou None).
    """
    if c is None:
        return (0, "Sem categoria", 0, "Sem subcategoria")
    if getattr(c, "nivel", None) == 1:
        return (c.id or 0, c.nome or "Sem categoria", c.id or 0, c.nome or "Sem subcategoria")
    pai = getattr(c, "categoria_pai", None)
    if pai:
        return (pai.id or 0, pai.nome or "Sem categoria", c.id or 0, c.nome or "Sem subcategoria")
    return (0, "Sem categoria", c.id or 0, c.nome or "Sem subcategoria")


def _agrupar_por_categoria(
    itens: Iterable,
    fonte: str,
    col_val: str,
    col_cat: str,
    ratear: bool = True,
) -> Tuple[List[Dict], Decimal]:
    """
    Agrupa os itens por categoria, rateando corretamente conforme membros.
    - Para cada membro, soma apenas a cota dele (valor dividido pelo número de membros).
    - Para o total geral, soma o valor total de cada transação/lançamento apenas uma vez.
    """
    total_geral = Decimal("0")
    macros: Dict[int, Dict] = {}
    objetos_somados = set()

    for obj in itens:
        # Rateio correto: divide pelo número de membros apenas se ratear=True
        if fonte == "cc":
            gasto = _valor_gasto_transacao(obj, col_val, ratear)
        else:
            gasto = _valor_gasto_lancamento(obj, col_val, ratear)

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

        # Para o total geral, soma o valor total da transação/lançamento apenas uma vez
        obj_id = getattr(obj, "id", None)
        if obj_id is not None and obj_id not in objetos_somados:
            if fonte == "cc":
                v = Decimal(getattr(obj, col_val, 0) or 0)
                if v < 0:
                    total_geral += abs(v)
            else:
                v = Decimal(getattr(obj, col_val, 0) or 0)
                total_geral += v
            objetos_somados.add(obj_id)

    # Ordenação alfabética das categorias e subcategorias
    out: List[Dict] = []
    for m in macros.values():
        subs = list(m["subs"].values())
        subs.sort(key=lambda x: x["nome"].lower())
        out.append({"id": m["id"], "nome": m["nome"], "total": m["total"], "subcats": subs})
    out.sort(key=lambda x: x["nome"].lower())

    return out, total_geral