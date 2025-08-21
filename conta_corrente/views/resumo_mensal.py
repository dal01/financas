# conta_corrente/views/resumo_mensal.py
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from conta_corrente.models import Conta, Transacao, RegraOcultacao


def _primeiro_dia_do_mes(dt: date) -> date:
    return dt.replace(day=1)

def _add_meses(dt: date, n: int) -> date:
    ano, mes = dt.year, dt.month
    total = ano * 12 + (mes - 1) + n
    novo_ano, novo_mes = divmod(total, 12)
    return date(novo_ano, novo_mes + 1, 1)

def _parse_ym(s: str) -> date | None:
    try:
        y, m = s.split("-")
        y, m = int(y), int(m)
        if 1 <= m <= 12:
            return date(y, m, 1)
    except Exception:
        pass
    return None

def _aplicar_ocultacao(qs, incluir_ocultas: bool):
    """
    Retorna qs com/sem itens ocultos (oculta_manual e regras).
    """
    if incluir_ocultas:
        return qs

    # Excluir ocultas manualmente
    qs = qs.exclude(oculta_manual=True)

    # Excluir por regras
    regras = list(RegraOcultacao.objects.filter(ativo=True))
    filtro_simples = Q()
    tem_simples = False
    regras_regex = []
    for r in regras:
        p = r.padrao
        if r.tipo_padrao == "exato":
            filtro_simples |= Q(descricao__iexact=p); tem_simples = True
        elif r.tipo_padrao == "contem":
            filtro_simples |= Q(descricao__icontains=p); tem_simples = True
        elif r.tipo_padrao == "inicia_com":
            filtro_simples |= Q(descricao__istartswith=p); tem_simples = True
        elif r.tipo_padrao == "termina_com":
            filtro_simples |= Q(descricao__iendswith=p); tem_simples = True
        elif r.tipo_padrao == "regex":
            regras_regex.append(r)

    if tem_simples:
        qs = qs.exclude(filtro_simples)
    for r in regras_regex:
        try:
            qs = qs.exclude(descricao__iregex=r.padrao)
        except Exception:
            pass

    return qs


def resumo_mensal(request):
    """
    Série mensal de Entradas, Saídas e Saldo.
    Params:
      - conta=<id> (opcional)
      - inicio=YYYY-MM & fim=YYYY-MM  (opcionais; priorizam sobre 'meses')
      - meses=N (default 12)
      - incluir_ocultas=1 (default não incluir)
      - format=json (para JSON; padrão HTML)
    """
    qs = Transacao.objects.select_related("conta", "conta__instituicao")

    # Conta (opcional)
    conta_id = request.GET.get("conta")
    conta = None
    if conta_id:
        conta = get_object_or_404(Conta, id=conta_id)
        qs = qs.filter(conta=conta)

    # Período
    hoje = date.today()
    inicio_qs = _parse_ym(request.GET.get("inicio", ""))
    fim_qs = _parse_ym(request.GET.get("fim", ""))

    if inicio_qs and fim_qs:
        start = _primeiro_dia_do_mes(inicio_qs)
        end = _add_meses(_primeiro_dia_do_mes(fim_qs), 1)  # exclusivo
    else:
        # Ano atual por padrão
        start = date(hoje.year, 1, 1)
        end = date(hoje.year + 1, 1, 1)  # exclusivo


    qs = qs.filter(data__gte=start, data__lt=end)

    # Ocultas?
    incluir_ocultas = request.GET.get("incluir_ocultas") == "1"
    qs = _aplicar_ocultacao(qs, incluir_ocultas)

    # Agrupar por mês
    agrupado = (
        qs.annotate(mes=TruncMonth("data"))
          .values("mes")
          .order_by("mes")
          .annotate(
              entradas=Sum("valor", filter=Q(valor__gt=0)),
              saidas=Sum("valor", filter=Q(valor__lt=0)),
              saldo=Sum("valor"),
          )
    )

    # Normalizar valores e montar série
    serie = []
    total_entradas = Decimal("0")
    total_saidas = Decimal("0")
    total_saldo = Decimal("0")
    for row in agrupado:
        e = row["entradas"] or Decimal("0")
        s = row["saidas"] or Decimal("0")
        t = row["saldo"] or Decimal("0")
        serie.append({
            "mes": row["mes"].strftime("%Y-%m"),
            "entradas": e,
            "saidas": s,
            "saldo": t,
        })
        total_entradas += e
        total_saidas += s
        total_saldo += t

    payload = {
        "inicio": start.strftime("%Y-%m"),
        "fim": _add_meses(end, -1).strftime("%Y-%m"),  # inclusivo
        "conta": conta.id if conta else None,
        "incluir_ocultas": incluir_ocultas,
        "serie": [
            {"mes": it["mes"], "entradas": str(it["entradas"]), "saidas": str(it["saidas"]), "saldo": str(it["saldo"])}
            for it in serie
        ],
        "totais": {
            "entradas": str(total_entradas),
            "saidas": str(total_saidas),
            "saldo": str(total_saldo),
        }
    }

    if request.GET.get("format") == "json":
        return JsonResponse(payload)

    # HTML
    contexto = {
        "conta": conta,
        "inicio": payload["inicio"],
        "fim": payload["fim"],
        "incluir_ocultas": incluir_ocultas,
        "serie": serie,
        "totais": {
            "entradas": total_entradas,
            "saidas": total_saidas,
            "saldo": total_saldo,
        },
    }
    return render(request, "conta_corrente/resumo_mensal.html", contexto)
