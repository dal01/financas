# relatorios/views/gastos_categorias.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
import calendar
from typing import Any, Dict

from django.db import models
from django.db.models import (
    Sum, Case, When, F, Value, Q,
    DecimalField, ExpressionWrapper, IntegerField, CharField
)
from django.shortcuts import render

from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

SENTINEL_SEM_CATEGORIA = 0  # para agrupar "Sem categoria"
IGNORAR_CATEGORIA_PAGTO_CARTAO = "Pagamentos de cartão"  # iexact


# =========================
# Período
# =========================
def _periodo(request):
    """
    Define o período a partir de GET:
      - modo=ano|mes (default: ano)
      - ano=YYYY (default: ano atual)
      - mes=1..12 (usado só quando modo=mes; default = mês atual)
    Retorna (dt_ini, dt_fim, contexto_ui)
    """
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
        label = f"{dt_ini:%B/%Y}".capitalize()
    else:
        # ano
        dt_ini = date(ano, 1, 1)
        dt_fim = date(ano, 12, 31)
        label = f"{ano}"

    ctx = {
        "modo": modo,
        "ano": ano,
        "mes": dt_ini.month if modo == "mes" else None,
        "periodo_label": label,
    }
    return dt_ini, dt_fim, ctx


# =========================
# Helpers de ocultação
# =========================
def _oculta_filter_kwargs(model) -> Dict[str, bool]:
    """
    Descobre automaticamente campos booleanos de 'ocultação' no model.
    Retorna dict {campo: True} para cada campo encontrado.
    """
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
    """
    Aplica exclude(campo=True) para todos os campos de ocultação detectados.
    Isso mantém registros com False **e NULL** no resultado e exclui apenas os marcados True.
    """
    kwargs = _oculta_filter_kwargs(model)
    for k, v in kwargs.items():
        qs = qs.exclude(**{k: v})
    return qs


# =========================
# Aggregators
# =========================
def _agg_conta_corrente(dt_ini: date, dt_fim: date):
    """
    Agrega despesas de Transacao:
      - Despesa = valor < 0 (somamos como positivo)
      - Ignora (valor >= 0)
      - Exclui itens marcados como ocultos (qualquer campo detectado)
      - Exclui categoria 'Pagamentos de cartão'
      - Agrupa por Macro/Sub usando categoria e seu pai
      - Considera 'Sem categoria' (mas só exibe se total > 0)
    """
    # amount = -valor quando valor < 0, senão 0
    amount_expr = Case(
        When(
            valor__lt=0,
            then=ExpressionWrapper(
                -F("valor"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        ),
        default=Value(Decimal("0.00")),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    # Macro/Sub calculados:
    macro_id_expr = Case(
        When(categoria__isnull=True, then=Value(SENTINEL_SEM_CATEGORIA)),
        When(categoria__categoria_pai__isnull=True, then=F("categoria_id")),      # categoria é macro
        default=F("categoria__categoria_pai_id"),                                  # sub: usa o pai
        output_field=IntegerField(),
    )
    macro_nome_expr = Case(
        When(categoria__isnull=True, then=Value("Sem categoria")),
        When(categoria__categoria_pai__isnull=True, then=F("categoria__nome")),    # macro
        default=F("categoria__categoria_pai__nome"),                               # sub -> nome do pai
        output_field=CharField(max_length=200),
    )
    sub_id_expr = Case(
        When(categoria__isnull=True, then=Value(None)),
        default=F("categoria_id"),
        output_field=IntegerField(),
    )
    sub_nome_expr = Case(
        When(categoria__isnull=True, then=Value("—")),
        default=F("categoria__nome"),
        output_field=CharField(max_length=200),
    )

    qs = (
        Transacao.objects
        .filter(data__gte=dt_ini, data__lte=dt_fim)
    )
    qs = _excluir_ocultas(qs, Transacao)
    qs = (
        qs.exclude(categoria__nome__iexact=IGNORAR_CATEGORIA_PAGTO_CARTAO)
          .values(
              macro_id=macro_id_expr,
              macro_nome=macro_nome_expr,
              sub_id=sub_id_expr,
              sub_nome=sub_nome_expr,
          )
          .annotate(total=Sum(amount_expr))
          .filter(~Q(macro_id=SENTINEL_SEM_CATEGORIA) | Q(total__gt=0))  # mantém "Sem categoria" só se total > 0
    )

    return list(qs)


def _agg_cartao(dt_ini: date, dt_fim: date):
    """
    Agrega despesas de Lancamento (cartão):
      - Despesa = valor > 0; estornos (valor < 0) abatem
      - Soma direta de 'valor'
      - Exclui itens marcados como ocultos (qualquer campo detectado)
      - Agrupa por Macro/Sub; considera 'Sem categoria' (mas só exibe se total > 0)
    """
    amount_expr = F("valor")  # positivo = despesa, negativo = estorno

    macro_id_expr = Case(
        When(categoria__isnull=True, then=Value(SENTINEL_SEM_CATEGORIA)),
        When(categoria__categoria_pai__isnull=True, then=F("categoria_id")),
        default=F("categoria__categoria_pai_id"),
        output_field=IntegerField(),
    )
    macro_nome_expr = Case(
        When(categoria__isnull=True, then=Value("Sem categoria")),
        When(categoria__categoria_pai__isnull=True, then=F("categoria__nome")),
        default=F("categoria__categoria_pai__nome"),
        output_field=CharField(max_length=200),
    )
    sub_id_expr = Case(
        When(categoria__isnull=True, then=Value(None)),
        default=F("categoria_id"),
        output_field=IntegerField(),
    )
    sub_nome_expr = Case(
        When(categoria__isnull=True, then=Value("—")),
        default=F("categoria__nome"),
        output_field=CharField(max_length=200),
    )

    qs = (
        Lancamento.objects
        .filter(data__gte=dt_ini, data__lte=dt_fim)
    )
    qs = _excluir_ocultas(qs, Lancamento)
    qs = (
        qs.values(
            macro_id=macro_id_expr,
            macro_nome=macro_nome_expr,
            sub_id=sub_id_expr,
            sub_nome=sub_nome_expr,
        )
        .annotate(total=Sum(
            amount_expr,
            output_field=DecimalField(max_digits=12, decimal_places=2)
        ))
        .filter(~Q(macro_id=SENTINEL_SEM_CATEGORIA) | Q(total__gt=0))
    )
    return list(qs)


# =========================
# Merge
# =========================
def _merge_aggregates(rows_cc, rows_ccard):
    """
    Junta os resultados de conta-corrente e cartão num único dicionário,
    somando os totais por (macro_id, sub_id).
    Retorna estrutura hierárquica para a template.
    """
    by_pair = {}  # (macro_id, sub_id) -> {macro_id, macro_nome, sub_id, sub_nome, total}
    for src in (rows_cc, rows_ccard):
        for r in src:
            key = (r["macro_id"], r["sub_id"])
            if key not in by_pair:
                by_pair[key] = {
                    "macro_id": r["macro_id"],
                    "macro_nome": r["macro_nome"],
                    "sub_id": r["sub_id"],
                    "sub_nome": r["sub_nome"],
                    "total": Decimal(r["total"] or 0),
                }
            else:
                by_pair[key]["total"] += Decimal(r["total"] or 0)

    # organiza por macro
    macros: Dict[Any, Dict[str, Any]] = {}
    for (macro_id, sub_id), r in by_pair.items():
        macro_key = macro_id
        macros.setdefault(macro_key, {
            "macro_id": macro_id,
            "macro_nome": r["macro_nome"],
            "total_macro": Decimal("0"),
            "subs": [],
        })
        macros[macro_key]["subs"].append({
            "sub_id": sub_id,
            "sub_nome": r["sub_nome"],
            "total": r["total"],
        })
        macros[macro_key]["total_macro"] += r["total"]

    # ordena: macros por nome; subs por nome
    macro_list = list(macros.values())
    for m in macro_list:
        m["subs"].sort(key=lambda x: (x["sub_nome"] or "").lower())
    macro_list.sort(key=lambda m: (m["macro_nome"] or "").lower())

    total_geral = sum((m["total_macro"] for m in macro_list), Decimal("0"))
    return macro_list, total_geral


# =========================
# View
# =========================
def gastos_por_categoria(request):
    """
    Relatório de gastos por Categoria/Subcategoria no período.
    - Modo: ano (default) ou mês
    - Exclui transações/lançamentos ocultos (detectados automaticamente)
    - Conta-corrente: apenas valor < 0 (despesa), somado como positivo
    - Cartão: valor com sinal (positivos somam, negativos abatem)
    """
    dt_ini, dt_fim, ctx_ui = _periodo(request)

    rows_cc = _agg_conta_corrente(dt_ini, dt_fim)
    rows_ccard = _agg_cartao(dt_ini, dt_fim)

    macros, total_geral = _merge_aggregates(rows_cc, rows_ccard)

    context = {
        **ctx_ui,
        "dt_ini": dt_ini,
        "dt_fim": dt_fim,
        "macros": macros,
        "total_geral": total_geral,
        "anos_disponiveis": list(range(date.today().year - 4, date.today().year + 1)),  # últimos 5 anos
        "meses": [
            (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"),
            (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
            (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
        ],
    }
    return render(request, "relatorios/gastos_categorias.html", context)
