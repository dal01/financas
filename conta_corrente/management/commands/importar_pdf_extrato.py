# conta_corrente/management/commands/importar_pdf_extrato.py
from pathlib import Path
from decimal import Decimal
from datetime import datetime, date
import re
import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import pdfplumber

from core.models import InstituicaoFinanceira
from conta_corrente.models import Conta, Transacao, RegraMembro


# ===== Helpers =====

# Ex.: "02/06/2025 021235 CRED PIX 1.000,00 C 4.519,34 C"
LINE_RE = re.compile(
    r"^(?P<data>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<doc>\S+)\s+"
    r"(?P<hist>.+?)\s+"
    r"(?P<valor>[-\d\.\,]+)\s+(?P<valor_cd>[CD])\s+"
    r"(?P<saldo>[-\d\.\,]+)\s+(?P<saldo_cd>[CD])$"
)

# Cabeçalho presente no seu PDF (ajuste se variar)
# "Conta: 00002 | 3701 | 000584985168-9"
CAB_RE = re.compile(r"Conta:\s*\S+\s*\|\s*(?P<ag>\d+)\s*\|\s*(?P<conta>[\d\-\.]+)")

def br_money_to_decimal(txt: str) -> Decimal:
    if txt is None:
        return Decimal("0")
    t = txt.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return Decimal("0")

def parse_data_br(d: str) -> date:
    return datetime.strptime(d, "%d/%m/%Y").date()

def fitid_from_fields(data: date, doc: str, hist: str, valor: Decimal) -> str:
    base = f"{data.isoformat()}|{doc}|{(hist or '').strip()}|{valor:.2f}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:28]
    return f"PDF{digest}"

def normaliza_historico(hist: str) -> str:
    return re.sub(r"\s+", " ", hist or "").strip()[:255]

def detecta_linha_extrato(line: str) -> dict | None:
    m = LINE_RE.match(line.strip())
    if not m:
        return None

    data = parse_data_br(m.group("data"))
    nr_doc = m.group("doc")
    hist = normaliza_historico(m.group("hist"))
    valor = br_money_to_decimal(m.group("valor"))
    cd = m.group("valor_cd")  # 'C' (crédito) ou 'D' (débito)
    saldo = br_money_to_decimal(m.group("saldo"))

    if cd.upper() == "D" and valor > 0:
        valor = -valor

    return {
        "data": data,
        "nr_doc": nr_doc,
        "historico": hist,
        "valor": valor,
        "saldo": saldo,
    }

def ler_linhas_pdf(caminho: Path) -> list[str]:
    linhas: list[str] = []
    with pdfplumber.open(str(caminho)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            for raw in txt.splitlines():
                line = (raw or "").strip()
                if line:
                    linhas.append(line)
    return linhas

def inferir_agencia_conta(linhas: list[str]) -> tuple[str | None, str | None]:
    for li in linhas[:40]:
        m = CAB_RE.search(li)
        if m:
            return m.group("ag"), m.group("conta")
    return None, None

def iter_lancamentos(linhas: list[str]):
    """
    Gera dicts de lançamentos a partir das linhas do PDF.
    Ignora cabeçalhos/rodapés comuns e 'SALDO DIA'.
    """
    for li in linhas:
        lli = li.lower()
        if lli.startswith("extrato") or "ouvidoria" in lli or "sac caixa" in lli:
            continue
        if lli.startswith("lançamentos do dia") or lli.startswith("lancamentos do dia"):
            continue
        if lli.startswith("data mov.") or lli.startswith("data mov"):
            continue
        if "saldo dia" in lli:  # linha de saldo do dia
            continue

        parsed = detecta_linha_extrato(li)
        if parsed:
            yield parsed


# ===== Regras de Membro (cache e aplicação) =====

def _carregar_regras_membro():
    """
    Carrega regras ativas ordenadas por prioridade. Retorna uma lista de dicts:
    {'tipo': str, 'padrao': str, 'padrao_low': str, 'regex': Pattern|None, 'membro_ids': [int,...]}
    """
    regras = []
    for r in RegraMembro.objects.filter(ativo=True).order_by("prioridade").prefetch_related("membros"):
        item = {
            "tipo": r.tipo_padrao,
            "padrao": r.padrao,
            "padrao_low": r.padrao.lower(),
            "regex": None,
            "membro_ids": list(r.membros.values_list("id", flat=True)),
        }
        if r.tipo_padrao == "regex":
            try:
                item["regex"] = re.compile(r.padrao, flags=re.IGNORECASE)
            except re.error:
                item["regex"] = None  # ignora regex inválida
        regras.append(item)
    return regras

def _aplicar_regras_membro_se_vazio(transacao: Transacao, regras_cache) -> bool:
    """
    Aplica a primeira regra que casar com a descrição apenas se a transação
    ainda NÃO tem membros. Não sobrescreve edições manuais.
    Retorna True se aplicou alguma regra.
    """
    if not hasattr(transacao, "membros"):
        return False
    if transacao.membros.exists():
        return False

    desc = (transacao.descricao or "").strip()
    if not desc:
        return False

    desc_low = desc.lower()
    for r in regras_cache:
        ok = (
            (r["tipo"] == "exato"       and desc_low == r["padrao_low"]) or
            (r["tipo"] == "contem"      and r["padrao_low"] in desc_low) or
            (r["tipo"] == "inicia_com"  and desc_low.startswith(r["padrao_low"])) or
            (r["tipo"] == "termina_com" and desc_low.endswith(r["padrao_low"])) or
            (r["tipo"] == "regex"       and r["regex"] is not None and r["regex"].search(desc) is not None)
        )
        if ok and r["membro_ids"]:
            transacao.membros.add(*r["membro_ids"])
            return True
    return False


# ===== Comando =====

class Command(BaseCommand):
    help = "Importa extratos bancários em PDF (texto) a partir de um arquivo ou de uma pasta por código de instituição."

    def add_arguments(self, parser):
        parser.add_argument(
            "--codigo",
            help="Código da instituição financeira (ex.: cx, bb, itau, nubank). Se informado, lê PDFs da pasta-base/codigo",
        )
        parser.add_argument(
            "--pasta-base",
            default=str(Path("conta_corrente") / "data"),
            help="Pasta base onde estão as subpastas por instituição (default: conta_corrente/data)",
        )
        parser.add_argument(
            "--arquivo",
            help="(Opcional) Caminho para um único PDF. Se informado, ignora --codigo/--pasta-base",
        )
        parser.add_argument(
            "--conta-numero",
            help="(Opcional) Número da conta (para vincular). Se ausente, tenta inferir do PDF.",
        )
        parser.add_argument(
            "--agencia",
            help="(Opcional) Agência; utilizada ao criar a conta automaticamente.",
        )
        parser.add_argument(
            "--titular",
            default="desconhecido",
            help="Titular para criação automática de conta (default: desconhecido).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar")
        parser.add_argument("--reset", action="store_true", help="Apaga lançamentos da conta antes de importar (uma vez por conta)")

    def handle(self, *args, **opts):
        arquivo = opts.get("arquivo")
        codigo = opts.get("codigo")
        pasta_base = Path(opts["pasta_base"]).resolve()
        agencia_cli = opts.get("agencia") or ""
        conta_num_cli = opts.get("conta_numero")
        titular = opts["titular"]
        dry_run = opts["dry_run"]
        do_reset = opts["reset"]

        arquivos: list[Path] = []

        if arquivo:
            p = Path(arquivo).resolve()
            if not p.exists():
                raise CommandError(f"Arquivo não encontrado: {p}")
            arquivos = [p]
            # Se veio arquivo único, precisa do código só para vincular à instituição
            if not codigo:
                raise CommandError("--codigo é obrigatório quando usa --arquivo (para achar a Instituição).")
        else:
            if not codigo:
                raise CommandError("Informe --codigo ou --arquivo.")
            pasta = pasta_base / codigo
            if not pasta.exists():
                raise CommandError(f"Pasta não encontrada: {pasta}")
            arquivos = sorted([p for p in pasta.rglob("*.pdf") if p.is_file()])
            if not arquivos:
                self.stdout.write(self.style.WARNING(f"⚠ Nenhum PDF encontrado em {pasta}"))
                return

        # Instituição
        try:
            inst = InstituicaoFinanceira.objects.get(codigo__iexact=codigo)
        except InstituicaoFinanceira.DoesNotExist:
            raise CommandError(f"Inexistente: Instituição '{codigo}'")

        total_arquivos = 0
        total_linhas_lidas = 0
        total_proc = 0
        total_novos = 0
        total_atualizados = 0
        total_nao_casou = 0

        # Para aplicar reset só uma vez por conta
        contas_resetadas: set[int] = set()

        # Regras (cache uma vez)
        regras_cache = _carregar_regras_membro()

        for caminho_pdf in arquivos:
            total_arquivos += 1
            try:
                rel = caminho_pdf.relative_to(pasta_base)
                nome_legivel = rel
            except Exception:
                nome_legivel = caminho_pdf
            self.stdout.write(self.style.NOTICE(f"→ Lendo: {nome_legivel}"))

            linhas = ler_linhas_pdf(caminho_pdf)
            total_linhas_lidas += len(linhas)

            ag_detect, conta_detect = inferir_agencia_conta(linhas)
            numero_conta = conta_num_cli or conta_detect or "desconhecido"
            agencia_final = (agencia_cli or ag_detect) or None

            conta, _created = Conta.objects.get_or_create(
                instituicao=inst,
                numero=numero_conta,
                defaults={"titular": titular, "agencia": agencia_final},
            )

            # Reset uma única vez por conta
            if do_reset and not dry_run and conta.id not in contas_resetadas:
                apagados, _ = Transacao.objects.filter(conta=conta).delete()
                contas_resetadas.add(conta.id)
                self.stdout.write(self.style.WARNING(f"🧹 Lançamentos apagados da conta {numero_conta}: {apagados}"))

            # Processar lançamentos
            reconhecidas_este_pdf = 0
            for parsed in iter_lancamentos(linhas):
                reconhecidas_este_pdf += 1

                data = parsed["data"]
                descricao = parsed["historico"]
                valor = parsed["valor"]
                saldo = parsed["saldo"]
                doc = parsed["nr_doc"]

                fitid = fitid_from_fields(data, doc, descricao, valor)

                if dry_run:
                    total_proc += 1
                    continue

                with transaction.atomic():
                    obj, created = Transacao.objects.update_or_create(
                        conta=conta,
                        fitid=fitid,
                        defaults={
                            "data": data,
                            "descricao": descricao,
                            "valor": valor,
                            "saldo": saldo,
                        },
                    )

                # Aplica regra somente se ainda não há membros (não sobrescreve edições)
                try:
                    _aplicar_regras_membro_se_vazio(obj, regras_cache)
                except Exception:
                    # não interrompe importação por erro de regra
                    pass

                if created:
                    total_novos += 1
                else:
                    total_atualizados += 1
                total_proc += 1

            # Estatística de reconhecimento por arquivo
            total_nao_casou += max(0, len(linhas) - reconhecidas_este_pdf)

        resumo = (
            f"📄 PDFs: {total_arquivos} | Linhas lidas: {total_linhas_lidas} | "
            f"Processadas: {total_proc} | Novas: {total_novos} | Atualizadas: {total_atualizados} | "
            f"Não reconhecidas: {total_nao_casou}"
        )
        if dry_run:
            resumo += " | (dry-run: nada gravado)"
        self.stdout.write(self.style.SUCCESS(resumo))
