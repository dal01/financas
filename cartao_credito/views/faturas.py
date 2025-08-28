from __future__ import annotations
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_POST

from cartao_credito.models import FaturaCartao, Lancamento, Cartao
from core.models import Membro

from cartao_credito.services.regras import aplicar_regras_em_lancamento, aplicar_regras_em_queryset


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
def faturas_list(request: HttpRequest):
    competencia = parse_competencia(request.GET.get("competencia"))
    q = (request.GET.get("q") or "").strip()

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

    soma_totais_pdf = (
        base.filter(total__isnull=False)
        .aggregate(s=Coalesce(Sum("total"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))))
        ["s"]
    ) or Decimal("0")

    ids_sem_total = base.filter(total__isnull=True).values_list("id", flat=True)
    soma_lancs_sem_total = (
        Lancamento.objects
        .filter(fatura_id__in=ids_sem_total)
        .aggregate(s=Coalesce(Sum("valor"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))))
        ["s"]
    ) or Decimal("0")

    soma_total_calculado = soma_totais_pdf + soma_lancs_sem_total
    total_faturas = base.count()

    meses_disponiveis = sorted(
        set(FaturaCartao.objects.values_list("competencia", flat=True)),
        reverse=True
    )

    base_com_calc = base.annotate(
        total_calc=Coalesce(
            Sum("lancamentos__valor"),
            Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))
        )
    )

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
        g["total"] += (total_display or Decimal("0"))

    grupos_membro = []
    for membro_nome in sorted(grupos.keys(), key=lambda s: s.lower()):
        dados = grupos[membro_nome]
        total_membro = dados["total"] or Decimal("0")
        grupos_membro.append({
            "membro": membro_nome,
            "linhas": dados["linhas"],
            "total_br": moeda_br(total_membro),
        })

    context = {
        "competencia": competencia.strftime("%Y-%m"),
        "card_qtd_faturas": total_faturas,
        "card_soma": moeda_br(soma_total_calculado),
        "card_pdf": moeda_br(soma_totais_pdf),
        "grupos_membro": grupos_membro,
        "meses_disponiveis": [d.strftime("%Y-%m") for d in meses_disponiveis],
        "q": q,
    }
    return render(request, "cartao_credito/faturas_list.html", context)


def fatura_detalhe(request: HttpRequest, fatura_id: str):
    fatura = get_object_or_404(
        FaturaCartao.objects.select_related("cartao", "cartao__instituicao", "cartao__membro"),
        pk=fatura_id
    )

    lancs = (
        Lancamento.objects
        .filter(fatura=fatura)
        .prefetch_related("membros")
        .order_by("data", "id")
    )

    soma = lancs.aggregate(soma=Coalesce(
        Sum("valor"),
        Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))
    ))["soma"] or Decimal("0")

    total_display = fatura.total if fatura.total is not None else soma

    linhas = []
    for l in lancs:
        linhas.append({
            "id": l.id,
            "data_br": data_br(l.data),
            "descricao": l.descricao,
            "valor_br": moeda_br(l.valor),
            "membros_ids": [m.id for m in l.membros.all()],
        })

    cartao = fatura.cartao
    bandeira = cartao.bandeira or "—"
    final = cartao.cartao_final
    membro_nome = cartao.membro.nome if cartao and cartao.membro_id else "—"
    instituicao = cartao.instituicao.nome if cartao and cartao.instituicao_id else "—"

    membros_options = list(Membro.objects.order_by("nome").values("id", "nome"))

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
        "membros": membros_options,
    }
    return render(request, "cartao_credito/fatura_detalhe.html", context)


@require_POST
def lancamento_toggle_membro(request: HttpRequest, lancamento_id: int):
    """Ativa/desativa 1 membro no lançamento (M2M)."""
    l = get_object_or_404(Lancamento, pk=lancamento_id)
    membro_id = request.POST.get("membro_id")
    m = get_object_or_404(Membro, pk=membro_id)

    if l.membros.filter(id=m.id).exists():
        l.membros.remove(m)
        ativo = False
    else:
        l.membros.add(m)
        ativo = True

    return JsonResponse({
        "ok": True,
        "lancamento_id": l.id,
        "membro_id": m.id,
        "ativo": ativo,
    })


@require_POST
def lancamento_toggle_todos(request: HttpRequest, lancamento_id: int):
    """Ativa/desativa todos os membros de uma vez."""
    l = get_object_or_404(Lancamento, pk=lancamento_id)
    membros = list(Membro.objects.all())

    # já tem todos? então limpa
    if l.membros.count() == len(membros):
        l.membros.clear()
        ativo = False
    else:
        l.membros.set(membros)
        ativo = True

    return JsonResponse({
        "ok": True,
        "lancamento_id": l.id,
        "todos": ativo,
    })


@require_POST
def regra_aplicar_lancamento(request: HttpRequest, lancamento_id: int):
    l = get_object_or_404(Lancamento, pk=lancamento_id)
    ids = aplicar_regras_em_lancamento(l)
    return JsonResponse({"ok": True, "lancamento_id": l.id, "membros_ids": ids})

@require_POST
def regra_aplicar_fatura(request: HttpRequest, fatura_id: int):
    fatura = get_object_or_404(FaturaCartao, pk=fatura_id)
    qs = Lancamento.objects.filter(fatura=fatura).order_by("data", "id").prefetch_related("membros")
    res = aplicar_regras_em_queryset(qs)
    return JsonResponse({"ok": True, "fatura_id": fatura.id, "result": res})
