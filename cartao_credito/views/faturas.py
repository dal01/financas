# cartao_credito/views/faturas.py
from __future__ import annotations
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import render, get_object_or_404

from cartao_credito.models import FaturaCartao, Lancamento, Cartao


# ---------------- helpers ----------------
def primeiro_dia_mes(dt: date) -> date:
    return dt.replace(day=1)

def parse_competencia(ym: str | None) -> date:
    """Recebe 'YYYY-MM' e devolve date no 1º dia do mês; senão mês atual."""
    hoje = date.today()
    base = primeiro_dia_mes(hoje)
    if not ym:
        return base
    try:
        y, m = ym.split("-")
        y, m = int(y), int(m)
        if 1 <= m <= 12:
            return date(y, m, 1)
    except Exception:
        pass
    return base

def moeda_br(v: Decimal | None) -> str:
    v = v or Decimal("0")
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def data_br(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "-"


# ---------------- views ----------------
def faturas_list(request):
    """
    Lista faturas por competência, com:
      - cards de totais no topo
      - AGRUPAMENTO POR MEMBRO: uma tabela por membro, com total na última linha
    Nada de cálculos na template.
    """
    competencia = parse_competencia(request.GET.get("competencia"))
    q = (request.GET.get("q") or "").strip()

    # Base SEM anotações (evita duplicação em agregações globais)
    base = (
        FaturaCartao.objects
        .filter(competencia=competencia)
        .select_related("cartao", "cartao__instituicao", "cartao__membro")
        .order_by("cartao__membro__nome", "cartao__bandeira", "cartao__cartao_final", "vencimento_em", "id")
    )

    if q:
        base = base.filter(
            Q(cartao__membro__nome__icontains=q) |
            Q(cartao__bandeira__icontains=q) |
            Q(cartao__cartao_final__icontains=q)
        )

    # ===== Cards (sem duplicar) =====
    # (A) soma das faturas com total preenchido (PDF)
    soma_totais_pdf = (
        base.filter(total__isnull=False)
        .aggregate(s=Coalesce(Sum("total"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))))
        ["s"]
    ) or Decimal("0")

    # (B) soma dos lançamentos das faturas cujo total é nulo
    ids_sem_total = base.filter(total__isnull=True).values_list("id", flat=True)
    soma_lancs_sem_total = (
        Lancamento.objects
        .filter(fatura_id__in=ids_sem_total)
        .aggregate(s=Coalesce(Sum("valor"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))))
        ["s"]
    ) or Decimal("0")

    soma_total_calculado = soma_totais_pdf + soma_lancs_sem_total
    total_faturas = base.count()

    # Meses disponíveis (para o <select>)
    meses_disponiveis = sorted(
        set(FaturaCartao.objects.values_list("competencia", flat=True)),
        reverse=True
    )

    # ===== AGRUPAMENTO POR MEMBRO =====
    # Para cada fatura, definimos "total_display": usa total do PDF se houver; senão soma calculada
    # Para evitar JOIN no loop, anotamos a soma de lançamentos por fatura
    base_com_calc = base.annotate(
        total_calc=Coalesce(
            Sum("lancamentos__valor"),
            Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))
        )
    )

    # Mapa: membro -> {"linhas": [...], "total": Decimal}
    grupos: dict[str, dict[str, object]] = {}

    for f in base_com_calc:
        cartao: Cartao = f.cartao
        membro_nome = cartao.membro.nome if cartao and cartao.membro_id else "—"
        bandeira = cartao.bandeira or "—"
        final = (cartao.cartao_final or "")[-8:]

        total_display = f.total if f.total is not None else f.total_calc

        g = grupos.setdefault(membro_nome, {"linhas": [], "total": Decimal("0")})
        g["linhas"].append({
            "bandeira": bandeira,
            "final": final,
            "competencia_br": data_br(f.competencia.replace(day=1)) if f.competencia else "-",
            "fechamento_br": data_br(f.fechado_em),
            "vencimento_br": data_br(f.vencimento_em),
            "total_br": moeda_br(total_display),
            "_total_dec": total_display or Decimal("0"),
            "id": f.pk,
        })
        g["total"] = (g["total"] or Decimal("0")) + (total_display or Decimal("0"))

    # Ordena membros pelo nome; e, dentro de cada membro, mantém a ordem já aplicada no queryset
    grupos_membro = []
    for membro_nome in sorted(grupos.keys(), key=lambda s: s.lower()):
        dados = grupos[membro_nome]
        total_membro = dados["total"] or Decimal("0")
        # linhas já vêm ordenadas pelo queryset
        linhas = dados["linhas"]
        grupos_membro.append({
            "membro": membro_nome,
            "linhas": linhas,
            "total_br": moeda_br(total_membro),
        })

    context = {
        "competencia": competencia.strftime("%Y-%m"),
        # cards
        "card_qtd_faturas": total_faturas,
        "card_soma": moeda_br(soma_total_calculado),  # “Total do mês (calculado)”
        "card_pdf": moeda_br(soma_totais_pdf),        # “Total nos PDFs”
        # grupos para renderizar tabelas por membro
        "grupos_membro": grupos_membro,
        # selects / busca
        "meses_disponiveis": [d.strftime("%Y-%m") for d in meses_disponiveis],
        "q": q,
    }
    return render(request, "cartao_credito/faturas_list.html", context)


def fatura_detalhe(request, fatura_id: str):
    """
    Mostra os lançamentos de uma fatura específica, com totais prontos.
    """
    fatura = get_object_or_404(
        FaturaCartao.objects.select_related("cartao", "cartao__instituicao", "cartao__membro"),
        pk=fatura_id
    )

    lancs = (
        Lancamento.objects
        .filter(fatura=fatura)
        .order_by("data", "id")
    )

    soma = lancs.aggregate(soma=Coalesce(
        Sum("valor"),
        Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))
    ))["soma"] or Decimal("0")

    # se a fatura já tiver total no cabeçalho, priorize-o para exibir
    total_display = fatura.total if fatura.total is not None else soma

    linhas = [{
        "data_br": data_br(l.data),
        "descricao": l.descricao,
        "valor_br": moeda_br(l.valor),
    } for l in lancs]

    cartao = fatura.cartao
    bandeira = cartao.bandeira or "—"
    final = cartao.cartao_final
    membro_nome = cartao.membro.nome if cartao and cartao.membro_id else "—"
    instituicao = cartao.instituicao.nome if cartao and cartao.instituicao_id else "—"

    context = {
        "fatura": {
            "id": fatura.pk,
            "instituicao": instituicao,
            "bandeira": bandeira,
            "membro": membro_nome,
            "cartao_final": final,
            "competencia_br": data_br(fatura.competencia.replace(day=1)) if fatura.competencia else "-",
            "fechamento_br": data_br(fatura.fechado_em),
            "vencimento_br": data_br(fatura.vencimento_em),
            "total_br": moeda_br(total_display),
            "qtde": len(linhas),
        },
        "linhas": linhas,
    }
    return render(request, "cartao_credito/fatura_detalhe.html", context)
