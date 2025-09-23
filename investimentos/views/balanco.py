from decimal import Decimal
from collections import defaultdict
from django.db.models import Prefetch
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from ..models import Investimento, SaldoInvestimento
from conta_corrente.models import Conta, Saldo
from passivos.models import Passivo, SaldoPassivo


@require_http_methods(["GET"])
def balanco(request):
    # Investimentos agrupados por membro
    membros = []
    investimentos_por_membro = defaultdict(list)
    total_investimentos_por_membro = defaultdict(lambda: Decimal("0"))
    total_investimentos_geral = Decimal("0")

    investimentos = (
        Investimento.objects.filter(ativo=True)
        .select_related("instituicao", "membro")
        .prefetch_related(
            Prefetch("saldos", queryset=SaldoInvestimento.objects.order_by("-data", "-id"))
        )
        .order_by("membro__nome", "instituicao__nome", "nome")
    )

    investimentos_context = []
    for inv in investimentos:
        saldo_mais_recente = inv.saldos.first()
        membro = inv.membro
        if membro not in membros:
            membros.append(membro)
        investimentos_por_membro[membro].append({
            "obj": inv,
            "saldo_mais_recente": saldo_mais_recente,
        })
        valor = saldo_mais_recente.valor if saldo_mais_recente else Decimal("0")
        total_investimentos_por_membro[membro] += valor
        total_investimentos_geral += valor

    # Contas agrupadas por membro
    contas_por_membro = defaultdict(list)
    total_contas_por_membro = defaultdict(lambda: Decimal("0"))
    total_contas_geral = Decimal("0")

    contas = (
        Conta.objects.all()
        .select_related("instituicao", "membro")
        .order_by("membro__nome", "instituicao__nome", "numero")
    )

    for conta in contas:
        saldo_mais_recente = Saldo.objects.filter(conta=conta).order_by("-data", "-id").first()
        membro = conta.membro
        contas_por_membro[membro].append({
            "obj": conta,
            "saldo_mais_recente": saldo_mais_recente,
        })
        valor = saldo_mais_recente.valor if saldo_mais_recente else Decimal("0")
        total_contas_por_membro[membro] += valor
        total_contas_geral += valor

    # Passivos: lista única
    passivos = (
        Passivo.objects.filter(ativo=True)
        .prefetch_related(
            Prefetch("saldos", queryset=SaldoPassivo.objects.order_by("-data", "-id"))
        )
        .order_by("nome")
    )
    passivos_context = []
    total_passivos_geral = Decimal("0")
    for passivo in passivos:
        saldo_mais_recente = passivo.saldos.first()
        passivos_context.append({
            "obj": passivo,
            "saldo_mais_recente": saldo_mais_recente,
        })
        valor = saldo_mais_recente.valor_devido if saldo_mais_recente else Decimal("0")
        total_passivos_geral += valor

    total_ativos_geral = total_investimentos_geral + total_contas_geral
    patrimonio_liquido_geral = total_ativos_geral - total_passivos_geral

    contexto = {
        "investimentos_por_membro": [(m, investimentos_por_membro[m]) for m in membros],
        "total_investimentos_por_membro": total_investimentos_por_membro,
        "total_investimentos_geral": total_investimentos_geral,
        "contas_por_membro": contas_por_membro,
        "total_contas_por_membro": total_contas_por_membro,
        "total_contas_geral": total_contas_geral,
        "passivos": passivos_context,
        "total_passivos_geral": total_passivos_geral,
        "total_ativos_geral": total_ativos_geral,
        "patrimonio_liquido_geral": patrimonio_liquido_geral,
    }
    return render(request, "investimentos/balanco.html", contexto)


@require_http_methods(["GET"])
def investimentos_list(request):
    qs = (
        Investimento.objects.filter(ativo=True)
        .select_related("instituicao", "membro")
        .prefetch_related(
            Prefetch("saldos", queryset=SaldoInvestimento.objects.order_by("-data"))
        )
        .order_by("instituicao__nome", "nome")
    )

    # soma dos últimos saldos de cada investimento
    total_geral = 0
    for inv in qs:
        ultimo = inv.saldo_mais_recente
        if ultimo:
            total_geral += ultimo.valor

    return render(
        request,
        "investimentos/lista.html",
        {"investimentos": qs, "total_geral": total_geral},
    )


@require_http_methods(["GET"])
def investimento_detalhe(request, pk: int):
    inv = get_object_or_404(
        Investimento.objects.select_related("instituicao", "membro"), pk=pk
    )
    saldos = inv.saldos.all()
    form = SaldoInvestimentoForm()
    return render(
        request,
        "investimentos/detalhe.html",
        {"inv": inv, "saldos": saldos, "form": form},
    )


@require_http_methods(["POST"])
def investimento_novo_saldo(request, pk: int):
    inv = get_object_or_404(Investimento, pk=pk)
    form = SaldoInvestimentoForm(request.POST)
    if form.is_valid():
        saldo = form.save(commit=False)
        saldo.investimento = inv
        try:
            saldo.save()
            messages.success(request, "Saldo registrado com sucesso.")
        except Exception as e:
            messages.error(request, f"Erro ao salvar: {e}")
    else:
        messages.error(request, "Verifique os campos do formulário.")
    return redirect("investimentos:investimento_detalhe", pk=inv.pk)
