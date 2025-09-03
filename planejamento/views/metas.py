from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render, get_object_or_404

from ..models import Meta
from .forms import MetaForm


def metas_list(request: HttpRequest) -> HttpResponse:
    """
    GET: lista metas com busca e paginação.
    POST: cria uma nova Meta (form da modal "Adicionar").
    Calcula total das metas filtradas na view (total_valor_filtro).
    """
    # --- criação via modal ---
    if request.method == "POST":
        form = MetaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Meta criada com sucesso.")
            return redirect("planejamento:metas_list")
        else:
            messages.error(request, "Corrija os erros do formulário e tente novamente.")
    else:
        form = MetaForm()

    # --- filtros ---
    busca = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    qs = Meta.objects.all()

    if busca:
        qs = qs.filter(Q(descricao__icontains=busca) | Q(observacoes__icontains=busca))
    if status:
        qs = qs.filter(status=status)

    # ordenação: status (ativas primeiro na prática), data, prioridade desc, descrição
    qs = qs.order_by("status", "data_alvo", "-prioridade", "descricao")

    # --- total do filtro (todas as linhas do queryset filtrado) ---
    total_valor_filtro = qs.aggregate(_total=Sum("valor_alvo"))["_total"] or Decimal("0")

    # --- paginação ---
    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # se houve POST com erro, sinaliza para reabrir a modal de criação
    open_modal = request.method == "POST" and not form.is_valid()

    context = {
        "form": form,  # usado também como base para o form da modal de edição (JS preenche valores)
        "page_obj": page_obj,
        "busca": busca,
        "status_sel": status,
        "open_modal": open_modal,
        "status_choices": Meta.Status.choices,
        "total_valor_filtro": total_valor_filtro,
    }
    return render(request, "planejamento/metas_list.html", context)


def meta_editar(request: HttpRequest, pk: str) -> HttpResponse:
    """
    POST: atualiza uma Meta (enviado pela modal de edição).
    Usa o mesmo MetaForm, mas 'instance=meta'.
    """
    meta = get_object_or_404(Meta, pk=pk)

    if request.method != "POST":
        messages.error(request, "Método não permitido.")
        return redirect("planejamento:metas_list")

    form = MetaForm(request.POST, instance=meta)
    if form.is_valid():
        form.save()
        messages.success(request, "Meta atualizada com sucesso.")
    else:
        # Como a modal de edição é preenchida por JS, em caso de erro mostramos mensagem genérica.
        # (Se quiser renderizar erros campo a campo, dá para devolver a página com flags e reabrir a modal.)
        messages.error(request, "Não foi possível salvar. Verifique os dados e tente novamente.")

    return redirect("planejamento:metas_list")
