from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from collections import OrderedDict

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

    qs = qs.exclude(oculta_manual=True)

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
    Seções:
      - Resumo geral (todas as contas dos membros no queryset)
      - Resumo por membro -> instituição -> conta, com totais
    Params:
      - conta=<id> (opcional; se passar, tudo se restringe a essa conta)
      - inicio=YYYY-MM & fim=YYYY-MM  (opcionais; priorizam sobre 'meses')
      - incluir_ocultas=1 (default não incluir)
      - format=json (para JSON; padrão HTML)
    """
    qs = Transacao.objects.select_related(
        "conta", "conta__instituicao", "conta__membro"
    )

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

    # -----------------------------
    # Séries mensais (geral)
    # -----------------------------
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

    serie = []
    total_entradas = Decimal("0")
    total_saidas = Decimal("0")
    total_saldo = Decimal("0")
    for row in agrupado:
        e = row["entradas"] or Decimal("0")
        s = row["saidas"] or Decimal("0")  # negativo
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

    # % poupado no período (geral)
    if total_entradas != 0:
        poupado_pct = (total_saldo / total_entradas * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        poupado_pct = Decimal("0.00")

    if poupado_pct < 0:
        poupado_pct_clamp = Decimal("0.00")
    elif poupado_pct > 100:
        poupado_pct_clamp = Decimal("100.00")
    else:
        poupado_pct_clamp = poupado_pct

    # -------------------------------------------
    # Resumo por membro -> instituição -> conta
    # (baseado em conta.membro)
    # -------------------------------------------
    agg_membro_conta = (
        qs.values(
            "conta__membro__id",
            "conta__membro__nome",
            "conta__instituicao__nome",
            "conta__numero",
            "conta_id",
        )
        .annotate(
            entradas=Sum("valor", filter=Q(valor__gt=0)),
            saidas=Sum("valor", filter=Q(valor__lt=0)),
            saldo=Sum("valor"),
        )
        .order_by("conta__membro__nome", "conta__instituicao__nome", "conta__numero")
    )

    # Estrutura hierárquica: membro -> [contas] + totais do membro + % poupado do membro
    por_membro = OrderedDict()
    for row in agg_membro_conta:
        membro_id = row["conta__membro__id"] or 0
        membro_nome = row["conta__membro__nome"] or "—"
        inst = row["conta__instituicao__nome"] or "—"
        numero = row["conta__numero"] or "—"

        e = row["entradas"] or Decimal("0")
        s = row["saidas"] or Decimal("0")
        t = row["saldo"] or Decimal("0")

        if membro_id not in por_membro:
            por_membro[membro_id] = {
                "membro_id": membro_id,
                "membro_nome": membro_nome,
                "contas": [],
                "totais": {"entradas": Decimal("0"), "saidas": Decimal("0"), "saldo": Decimal("0")},
            }

        por_membro[membro_id]["contas"].append({
            "conta_id": row["conta_id"],
            "instituicao": inst,
            "numero": numero,
            "entradas": e,
            "saidas": s,
            "saldo": t,
        })
        por_membro[membro_id]["totais"]["entradas"] += e
        por_membro[membro_id]["totais"]["saidas"] += s
        por_membro[membro_id]["totais"]["saldo"] += t

    # Calcula % poupado por membro (e clamp 0–100)
    for m in por_membro.values():
        ent = m["totais"]["entradas"]
        sal = m["totais"]["saldo"]
        if ent != 0:
            pct = (sal / ent * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            pct = Decimal("0.00")
        if pct < 0:
            pct_clamp = Decimal("0.00")
        elif pct > 100:
            pct_clamp = Decimal("100.00")
        else:
            pct_clamp = pct
        m["poupado_pct"] = pct
        m["poupado_pct_clamp"] = pct_clamp

    # Payload comum (JSON)
    payload = {
        "inicio": start.strftime("%Y-%m"),
        "fim": _add_meses(end, -1).strftime("%Y-%m"),
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
            "poupado_pct": str(poupado_pct),
            "poupado_pct_clamp": str(poupado_pct_clamp),
        },
        "por_membro": [
            {
                "membro_id": m["membro_id"],
                "membro_nome": m["membro_nome"],
                "totais": {
                    "entradas": str(m["totais"]["entradas"]),
                    "saidas": str(m["totais"]["saidas"]),
                    "saldo": str(m["totais"]["saldo"]),
                },
                "poupado_pct": str(m["poupado_pct"]),
                "poupado_pct_clamp": str(m["poupado_pct_clamp"]),
                "contas": [
                    {
                        "conta_id": c["conta_id"],
                        "instituicao": c["instituicao"],
                        "numero": c["numero"],
                        "entradas": str(c["entradas"]),
                        "saidas": str(c["saidas"]),
                        "saldo": str(c["saldo"]),
                    }
                    for c in m["contas"]
                ],
            }
            for m in por_membro.values()
        ],
    }

    if request.GET.get("format") == "json":
        return JsonResponse(payload)

    # Contexto HTML
    contexto = {
        "conta": conta,
        "inicio": payload["inicio"],
        "fim": payload["fim"],
        "incluir_ocultas": incluir_ocultas,
        "serie": serie,
        # Resumo geral
        "totais": {
            "entradas": total_entradas,
            "saidas": total_saidas,
            "saldo": total_saldo,
            "poupado_pct": poupado_pct,
            "poupado_pct_clamp": poupado_pct_clamp,
        },
        # Resumo por membro (hierárquico)
        "por_membro": [
            {
                "membro_id": m["membro_id"],
                "membro_nome": m["membro_nome"],
                "totais": {
                    "entradas": m["totais"]["entradas"],
                    "saidas": m["totais"]["saidas"],
                    "saldo": m["totais"]["saldo"],
                },
                "poupado_pct": m["poupado_pct"],
                "poupado_pct_clamp": m["poupado_pct_clamp"],
                "contas": m["contas"],
            }
            for m in por_membro.values()
        ],
    }
    return render(request, "conta_corrente/resumo_mensal.html", contexto)
