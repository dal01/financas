from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from ..models import Investimento, SaldoInvestimento
from conta_corrente.models import Conta, Saldo
from passivos.models import Passivo, SaldoPassivo  # ajuste aqui
from ..forms import SaldoInvestimentoForm


@require_http_methods(["GET"])
def balanco(request):
    # Investimentos
    investimentos = (
        Investimento.objects.filter(ativo=True)
        .select_related("instituicao", "membro")
        .prefetch_related(
            Prefetch("saldos", queryset=SaldoInvestimento.objects.order_by("-data"))
        )
        .order_by("instituicao__nome", "nome")
    )
    total_investimentos = 0
    for inv in investimentos:
        ultimo = inv.saldo_mais_recente
        if ultimo:
            total_investimentos += ultimo.valor

    # Contas Correntes
    contas = (
        Conta.objects.all()
        .select_related("instituicao", "membro")
        .order_by("instituicao__nome", "numero")
    )

    def saldo_mais_recente_conta(conta):
        saldo = Saldo.objects.filter(conta=conta).order_by("-data", "-id").first()
        return saldo.valor if saldo else 0

    total_contas = sum(saldo_mais_recente_conta(c) for c in contas)

    # Passivos
    passivos = (
        Passivo.objects.filter(ativo=True)
        .prefetch_related(
            Prefetch("saldos", queryset=SaldoPassivo.objects.order_by("-data"))
        )
        .order_by("nome")
    )

    def saldo_mais_recente_passivo(passivo):
        saldo = SaldoPassivo.objects.filter(passivo=passivo).order_by("-data", "-id").first()
        return saldo.valor_devido if saldo else 0

    total_passivos = sum(saldo_mais_recente_passivo(p) for p in passivos)

    total_ativos = total_investimentos + total_contas
    patrimonio_liquido = total_ativos - total_passivos

    contexto = {
        "investimentos": investimentos,
        "contas": contas,
        "passivos": passivos,
        "total_investimentos": total_investimentos,
        "total_contas": total_contas,
        "total_passivos": total_passivos,
        "total_ativos": total_ativos,
        "patrimonio_liquido": patrimonio_liquido,
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
