# conta_corrente/management/commands/importar_ofx.py

from __future__ import annotations

from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
import re
import hashlib
from io import BytesIO

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from ofxparse import OfxParser

from core.models import InstituicaoFinanceira
from conta_corrente.models import Conta, Transacao
from conta_corrente.models import RegraMembro


# ---------------------------
# Pré-processamento do OFX (injeta FITID quando faltar)
# ---------------------------
STMTTRN_RE = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE)
def TAG_RE(tag: str) -> re.Pattern[str]:
    # Match com e sem fechamento (XML/SGML), captura conteúdo do grupo 1
    return re.compile(
        rf"<{tag}>\s*([^<\r\n]+)",
        re.IGNORECASE
    )

def _tag_value(block: str, tag: str) -> str | None:
    m = TAG_RE(tag).search(block)
    return (m.group(1).strip() if m else None)

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _inject_fitid_if_missing(block: str, idx_global: int) -> str:
    """
    Garante que exista <FITID> no bloco <STMTTRN>.
    Se não existir, gera um determinístico a partir de data/valor/memo/name + idx.
    """
    if TAG_RE("FITID").search(block):
        return block  # já tem

    dt = _tag_value(block, "DTPOSTED") or ""
    amt = _tag_value(block, "TRNAMT") or ""
    name = _tag_value(block, "NAME") or ""
    memo = _tag_value(block, "MEMO") or ""
    checknum = _tag_value(block, "CHECKNUM") or ""

    raw = f"{dt}|{amt}|{name}|{memo}|{checknum}|#{idx_global}"
    fitid = _sha1(raw)[:28]  # curto para evitar exageros

    # injeta logo após <STMTTRN>
    block_fixed = re.sub(
        r"(?i)<STMTTRN>",
        f"<STMTTRN>\n<FITID>{fitid}\n",
        block,
        count=1,
    )
    return block_fixed

def preprocess_ofx(content_bytes: bytes) -> bytes:
    """
    Normaliza encoding/linhas e injeta FITID quando ausente em STMTTRN.
    Mantém o restante intacto para o ofxparse.
    """
    # tenta UTF-8 e cai para Latin-1
    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = content_bytes.decode("latin-1")

    # normaliza quebras
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # injeta nos blocos
    idx = 0
    parts: list[str] = []
    last_end = 0
    for m in STMTTRN_RE.finditer(text):
        parts.append(text[last_end:m.start()])
        bloco = m.group(0)
        inner = m.group(1)
        bloco_fixed = _inject_fitid_if_missing(bloco, idx)
        parts.append(bloco_fixed)
        last_end = m.end()
        idx += 1
    parts.append(text[last_end:])

    text2 = "".join(parts)
    return text2.encode("utf-8")


# ---------------------------
# Helpers de FITID/descrição
# ---------------------------
def _compose_descricao(tx) -> str:
    """
    Monta uma descrição curta e informativa. Limite 255 chars.
    Ordem de preferência de ofxparse.Transaction:
      - NAME (ou payee)
      - MEMO
      - CHECKNUM
      - TYPE (se útil)
    """
    partes: list[str] = []

    # Alguns extratos populam payee, outros name
    name = getattr(tx, "name", None) or getattr(tx, "payee", None)
    memo = getattr(tx, "memo", None)
    checknum = getattr(tx, "checknum", None)
    ttype = getattr(tx, "type", None)

    if name:
        partes.append(str(name).strip())
    if memo and str(memo).strip() and (not name or str(memo).strip() != str(name).strip()):
        partes.append(str(memo).strip())
    if checknum:
        partes.append(f"cheque {checknum}")
    # evita poluir com tipos genéricos repetidos
    if ttype and str(ttype).strip().lower() not in {"other", "debit", "credit"}:
        partes.append(str(ttype).strip())

    descr = " — ".join(p for p in partes if p)[:255]
    return descr or ""


def _fitid_unique_real(original_fitid: str, data: date, valor: Decimal) -> str:
    """
    Sufixa o FITID quando há colisão com data/valor diferentes (bancos reaproveitam ids).
    """
    # garante 2 casas e inteiro de centavos estável
    cents = int((valor.copy_abs().quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100))
    base = original_fitid or "NOFITID"
    return f"{base}__{data:%Y%m%d}_{cents}"


# === NOVO: carregar e aplicar regras de membros ===============================
def _carregar_regras_membro():
    """
    Carrega regras ativas ordenadas por prioridade. Retorna lista de dicts:
    {'tipo': str, 'padrao': str, 'regex': Pattern|None, 'membro_ids': [int,...]}
    """
    regras = []
    qs = (
        RegraMembro.objects
        .filter(ativo=True)
        .order_by("prioridade")
        .prefetch_related("membros")
    )
    for r in qs:
        item = {
            "tipo": r.tipo_padrao,
            "padrao": r.padrao or "",
            "padrao_low": (r.padrao or "").lower(),
            "regex": None,
            "membro_ids": list(r.membros.values_list("id", flat=True)),
        }
        if r.tipo_padrao == "regex" and r.padrao:
            try:
                item["regex"] = re.compile(r.padrao, flags=re.IGNORECASE)
            except re.error:
                item["regex"] = None  # ignora regex inválida
        regras.append(item)
    return regras

def _aplicar_regras_membro_se_vazio(transacao: Transacao, regras_cache) -> bool:
    """
    Aplica a primeira regra que casar com a descrição **apenas se** a transação
    ainda não tiver membros. Retorna True se aplicou, False caso contrário.
    """
    # Se já há membros, respeita edição manual e não faz nada
    if hasattr(transacao, "membros") and transacao.membros.exists():
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
            # adiciona membros; não limpa nada para permitir ajustes manuais futuros
            transacao.membros.add(*r["membro_ids"])
            return True
    return False
# ==============================================================================


# ---------------------------
# Comando de importação
# ---------------------------
class Command(BaseCommand):
    help = "Importa arquivos .ofx de conta corrente, evitando duplicatas pelo FITID."

    def add_arguments(self, parser):
        parser.add_argument("codigo", help="Código da InstituiçãoFinanceira (ex.: bb, itau, nubank)")
        parser.add_argument("pasta_base", help="Pasta base onde ficam os OFX. O comando procura em <pasta_base>/<codigo>.")
        parser.add_argument("--dry-run", action="store_true", help="Não grava no banco; apenas simula a importação.")
        parser.add_argument("--reset", action="store_true", help="Apaga transações existentes de cada conta antes de importar.")

    def handle(self, *args, **opts):
        codigo = opts["codigo"]
        pasta_base = Path(opts["pasta_base"]).resolve()
        pasta = pasta_base / codigo
        dry_run = opts["dry_run"]
        do_reset = opts["reset"]

        if not pasta.exists():
            raise CommandError(f"Pasta não encontrada: {pasta}")

        try:
            inst = InstituicaoFinanceira.objects.get(codigo__iexact=codigo)
        except InstituicaoFinanceira.DoesNotExist:
            raise CommandError(f"Inexistente: Instituição '{codigo}'")

        arquivos = sorted(pasta.rglob("*.ofx"))
        if not arquivos:
            self.stdout.write(self.style.WARNING(f"⚠ Nenhum OFX encontrado em {pasta}"))
            return

        total_proc = 0
        total_novos = 0
        total_atualizados = 0
        total_pulados_sem_data = 0
        total_pulados_saldo_anterior = 0

        contas_resetadas: set[int] = set()

        # cache de regras por performance
        regras_cache = _carregar_regras_membro()

        for caminho in arquivos:
            self.stdout.write(self.style.NOTICE(f"→ Lendo: {caminho.relative_to(pasta_base)}"))

            raw = caminho.read_bytes()
            fixed = preprocess_ofx(raw)
            ofx = OfxParser.parse(BytesIO(fixed))

            contas = getattr(ofx, "accounts", None) or [getattr(ofx, "account", None)]
            contas = [c for c in contas if c is not None]

            for conta_ofx in contas:
                numero = (
                    (conta_ofx.number or getattr(conta_ofx, "account_id", "desconhecido"))
                    .strip()
                )

                conta, _ = Conta.objects.get_or_create(
                    instituicao=inst,
                    numero=numero,
                    defaults={"titular": "desconhecido"},
                )

                # RESET por conta (uma vez)
                if do_reset and not dry_run and conta.id not in contas_resetadas:
                    apagados, _ = Transacao.objects.filter(conta=conta).delete()
                    self.stdout.write(self.style.WARNING(f"🧹 Lançamentos apagados da conta {numero}: {apagados}"))
                    contas_resetadas.add(conta.id)

                # Importa transações
                for tx in conta_ofx.statement.transactions:
                    data = tx.date
                    if isinstance(data, datetime):
                        data = data.date()
                    if data is None:
                        total_pulados_sem_data += 1
                        continue

                    descricao = _compose_descricao(tx)

                    # pular "Saldo Anterior"
                    desc_base = (getattr(tx, "memo", "") or getattr(tx, "payee", "") or getattr(tx, "name", "") or "").strip().lower()
                    if "saldo anterior" in desc_base:
                        total_pulados_saldo_anterior += 1
                        continue

                    valor = Decimal(str(tx.amount))
                    fitid_original = getattr(tx, "id", None) or getattr(tx, "fitid", None) or ""

                    # FITID estendido se colisão com data/valor diferentes
                    fitid_para_usar = fitid_original
                    if fitid_original:
                        existing = (
                            Transacao.objects
                            .filter(conta=conta, fitid=fitid_original)
                            .only("id", "data", "valor")
                            .first()
                        )
                        if existing and (existing.data != data or existing.valor != valor):
                            fitid_para_usar = _fitid_unique_real(fitid_original, data, valor)
                    else:
                        # segurança extra: se, mesmo após preprocess, algo veio sem FITID
                        fitid_para_usar = _fitid_unique_real("NOFITID", data, valor)

                    if not dry_run:
                        with transaction.atomic():
                            obj, created = Transacao.objects.update_or_create(
                                conta=conta,
                                fitid=fitid_para_usar,
                                defaults={
                                    "data": data,
                                    "descricao": descricao,
                                    "valor": valor,
                                },
                            )

                            # aplica regra somente se não há membros
                            try:
                                _aplicar_regras_membro_se_vazio(obj, regras_cache)
                            except Exception:
                                # não interrompe importação por eventual erro de regra
                                pass

                        if created:
                            total_novos += 1
                        else:
                            total_atualizados += 1

                    total_proc += 1

        resumo = (
            f"✅ Processadas: {total_proc} | Novas: {total_novos} | Atualizadas: {total_atualizados}"
        )
        if dry_run:
            resumo += " | (dry-run: nada gravado)"
        if total_pulados_sem_data:
            resumo += f" | Puladas sem data: {total_pulados_sem_data}"
        if total_pulados_saldo_anterior:
            resumo += f" | Ignoradas 'Saldo Anterior': {total_pulados_saldo_anterior}"

        self.stdout.write(self.style.SUCCESS(resumo))
