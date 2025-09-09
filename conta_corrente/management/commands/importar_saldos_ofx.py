# conta_corrente/management/commands/importar_saldos_ofx.py
from __future__ import annotations

import os
import re
import pathlib
from datetime import datetime, date
from typing import Iterable, Optional, Tuple, List
from xml.etree import ElementTree as ET

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from conta_corrente.models import Conta, Saldo  # Saldo: FK p/ Conta, campos {data, valor}


# ----------------------------
# Utilidades de leitura/parse
# ----------------------------
def _read_text(path: pathlib.Path) -> str:
    """OFX BR geralmente vem em Latin-1/CP1252; tentamos em cascata."""
    for enc in ("latin-1", "cp1252", "utf-8"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1", errors="ignore")


def _extract_ofx_xml(content: str) -> str:
    """Para OFX 2.x com XML: recorta <OFX> ...</OFX>."""
    start = content.find("<OFX>")
    if start == -1:
        raise ValueError("Sem tag <OFX> (pode ser OFX 1.x/SGML).")
    return content[start:]


def _parse_ofx_date(dt: str) -> date:
    """Converte 'YYYYMMDDHHMMSS[-3:BRT]' ou 'YYYYMMDD' em date."""
    if not dt:
        raise ValueError("Data OFX vazia.")
    clean = dt.split("[", 1)[0].split(".", 1)[0]
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            pass
    return datetime.strptime(clean[:8], "%Y%m%d").date()


def _find_text(elem: ET.Element, path: str) -> Optional[str]:
    node = elem.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return None


def _iter_stmt_blocks(root: ET.Element) -> Iterable[ET.Element]:
    """Blocos de extrato corrente/poupança (XML)."""
    yield from root.findall(".//STMTRS")


def _get_account_info(stmt: ET.Element) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(BANKID, BRANCHID, ACCTID)."""
    bankid = _find_text(stmt, "BANKACCTFROM/BANKID")
    branch = _find_text(stmt, "BANKACCTFROM/BRANCHID")
    acctid = _find_text(stmt, "BANKACCTFROM/ACCTID")
    return bankid, branch, acctid


def _get_ledger_balance(stmt: ET.Element) -> Tuple[Optional[str], Optional[str]]:
    """(BALAMT, DTASOF) do LEDGERBAL (contábil)."""
    valor = _find_text(stmt, "LEDGERBAL/BALAMT")
    dtasof = _find_text(stmt, "LEDGERBAL/DTASOF")
    return valor, dtasof


# ----------------------------
# Fallback SGML-lite (regex)
# ----------------------------
SGML_STMT_RE = re.compile(
    r"<STMTRS>(?P<body>.*?)(?=<STMTRS>|</BANKMSGSRSV1>|</OFX>|$)",
    flags=re.DOTALL | re.IGNORECASE,
)

def _sgml_get(tag: str, text: str) -> Optional[str]:
    # Em SGML, linhas podem ser "<TAG>valor" sem fechamento
    m = re.search(rf"<{tag}>\s*([^\r\n<]+)", text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None

def _parse_sgml_ledgers(content: str) -> List[Tuple[Optional[str], Optional[str], Optional[str]]]:
    """
    Retorna lista de tuplas (acctid, balamt, dtasof) para cada STMTRS.
    Ignora transações/FITID completamente.
    """
    results: List[Tuple[Optional[str], Optional[str], Optional[str]]] = []
    # Primeiro tenta separar por STMTRS; se não achar, usa o bloco inteiro
    stmts = SGML_STMT_RE.findall(content) or [content]
    for body in stmts:
        acctid = _sgml_get("ACCTID", body)
        balamt = _sgml_get("BALAMT", body)  # espera o do LEDGERBAL; BB costuma ter um por STMTRS
        dtasof = _sgml_get("DTASOF", body)  # o primeiro DTASOF após LEDGERBAL costuma ser o certo
        # Heurística: se houver múltiplos BALAMT (ex.: AVAILBAL), preferimos o que aparece depois de "<LEDGERBAL>"
        led_section = re.search(r"<LEDGERBAL>(.*?)($|<\w+>)", body, flags=re.DOTALL | re.IGNORECASE)
        if led_section:
            bal_led = _sgml_get("BALAMT", led_section.group(1)) or balamt
            dt_led = _sgml_get("DTASOF", led_section.group(1)) or dtasof
            balamt, dtasof = bal_led, dt_led
        results.append((acctid, balamt, dtasof))
    return results


# ----------------------------
# Resolução de conta
# ----------------------------
def _resolver_conta(acctid: str, branch: Optional[str], agencia_prioritaria: Optional[str]) -> Tuple[Optional[Conta], str]:
    avisos = []
    agencia = branch or agencia_prioritaria
    qs = Conta.objects.filter(numero=str(acctid))
    if agencia:
        qs = qs.filter(agencia=str(agencia))
    contas = list(qs[:3])

    if not contas:
        qs_numero = list(Conta.objects.filter(numero=str(acctid))[:3])
        if len(qs_numero) == 1:
            avisos.append(f"Conta encontrada apenas por numero={acctid} (sem agencia).")
            return qs_numero[0], "; ".join(avisos)
        return None, f"Conta não encontrada (numero={acctid}, agencia={agencia})."

    if len(contas) > 1:
        return None, (
            f"Conta ambígua para numero={acctid}, agencia={agencia} "
            f"(foram encontradas {len(contas)}). Ajuste os cadastros."
        )

    return contas[0], "; ".join(avisos)


# ----------------------------
# Comando principal
# ----------------------------
class Command(BaseCommand):
    help = "Importa saldos contábeis (LEDGERBAL) de arquivos OFX em conta_corrente.Saldo (1 por conta/dia)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", dest="diretorio", help="Pasta base com arquivos .ofx (varredura recursiva).")
        parser.add_argument("arquivos", nargs="*", help="Arquivo(s) .ofx adicionais (opcional).")
        parser.add_argument("--agencia-prioritaria", dest="agencia_prioritaria", help="Usada quando o OFX não traz BRANCHID.")
        parser.add_argument("--dry-run", action="store_true", help="Não grava no banco — só mostra o que faria.")

    @transaction.atomic
    def handle(self, *args, **opts):
        diretorio: Optional[str] = opts.get("diretorio")
        arquivos_cli: List[str] = opts.get("arquivos") or []
        agencia_prioritaria: Optional[str] = opts.get("agencia_prioritaria")
        dry: bool = bool(opts.get("dry_run"))

        # 1) Coletar caminhos
        caminhos: List[pathlib.Path] = []
        if diretorio:
            base = pathlib.Path(diretorio)
            if not base.exists():
                raise CommandError(f"Pasta não encontrada: {base}")
            for root, _, files in os.walk(base):
                for f in files:
                    if f.lower().endswith(".ofx"):
                        caminhos.append(pathlib.Path(root) / f)
        for arq in arquivos_cli:
            p = pathlib.Path(arq)
            if p.exists() and p.suffix.lower() == ".ofx":
                caminhos.append(p)

        if not caminhos:
            raise CommandError("Nenhum arquivo OFX encontrado (use --dir ou informe arquivos).")

        # 2) Processamento
        total_files = 0
        total_new = 0
        total_upd = 0
        total_warn = 0

        for path in sorted(caminhos):
            file_new = 0
            file_upd = 0
            file_warn = 0

            raw = _read_text(path)

            # ---------- TENTATIVA 1: XML ----------
            root = None
            try:
                xml = _extract_ofx_xml(raw)
                root = ET.fromstring(xml)  # se falhar, cai para ofxparse/SGML
            except Exception:
                root = None

            if root is not None:
                # XML padrão
                for stmt in _iter_stmt_blocks(root):
                    bankid, branch, acctid = _get_account_info(stmt)
                    if not acctid:
                        self.stderr.write(self.style.WARNING(f"[{path.name}] Bloco sem ACCTID; ignorado."))
                        file_warn += 1
                        continue

                    bal_amt, bal_dt = _get_ledger_balance(stmt)
                    if bal_amt is None or bal_dt is None:
                        self.stderr.write(self.style.WARNING(
                            f"[{path.name}] Conta {acctid}: LEDGERBAL incompleto; ignorado."
                        ))
                        file_warn += 1
                        continue

                    try:
                        data_saldo = _parse_ofx_date(bal_dt)
                    except Exception:
                        self.stderr.write(self.style.WARNING(
                            f"[{path.name}] Conta {acctid}: data inválida '{bal_dt}'; ignorado."
                        ))
                        file_warn += 1
                        continue

                    conta, warn = _resolver_conta(acctid, branch, agencia_prioritaria)
                    if warn:
                        self.stderr.write(self.style.WARNING(f"[{path.name}] {warn}"))
                        file_warn += 1
                    if not conta:
                        continue

                    try:
                        valor = round(float(str(bal_amt).replace(",", ".")), 2)
                    except Exception:
                        self.stderr.write(self.style.WARNING(
                            f"[{path.name}] Conta {acctid}: valor inválido '{bal_amt}'; ignorado."
                        ))
                        file_warn += 1
                        continue

                    if dry:
                        self.stdout.write(
                            f"[DRY] {path.name} -> Conta {conta.id} ({conta.numero}/{conta.agencia}) "
                            f"{data_saldo} = {valor:.2f}"
                        )
                        file_new += 1
                    else:
                        obj, created = Saldo.objects.update_or_create(
                            conta=conta,
                            data=data_saldo,
                            defaults={"valor": valor},
                        )
                        if created:
                            file_new += 1
                        else:
                            file_upd += 1

            else:
                # ---------- TENTATIVA 2: ofxparse (SGML completo) ----------
                parsed = False
                try:
                    import ofxparse  # type: ignore
                    with open(path, "rb") as fh:
                        ofx = ofxparse.OfxParser.parse(fh)
                    parsed = True
                except Exception as e:
                    # Pode falhar por FITID vazio etc. — seguimos para SGML-lite
                    self.stderr.write(self.style.WARNING(f"[{path.name}] ofxparse falhou: {e}"))

                if parsed and getattr(ofx, "accounts", None):
                    for account in ofx.accounts:
                        acctid = getattr(account, "account_id", None) or getattr(account, "number", None)
                        branch = None
                        if not acctid:
                            self.stderr.write(self.style.WARNING(f"[{path.name}] Conta sem ACCTID; ignorada."))
                            file_warn += 1
                            continue

                        st = getattr(account, "statement", None)
                        bal = getattr(st, "ledger_balance", None) if st else None
                        bal_date = getattr(st, "ledger_balance_date", None) if st else None
                        if bal is None or bal_date is None:
                            self.stderr.write(self.style.WARNING(f"[{path.name}] Conta {acctid}: sem LEDGERBAL; ignorado."))
                            file_warn += 1
                            continue

                        data_saldo = bal_date.date() if hasattr(bal_date, "date") else bal_date
                        conta, warn = _resolver_conta(acctid, branch, agencia_prioritaria)
                        if warn:
                            self.stderr.write(self.style.WARNING(f"[{path.name}] {warn}"))
                            file_warn += 1
                        if not conta:
                            continue

                        try:
                            valor = round(float(bal), 2)
                        except Exception:
                            self.stderr.write(self.style.WARNING(
                                f"[{path.name}] Conta {acctid}: valor inválido '{bal}'; ignorado."
                            ))
                            file_warn += 1
                            continue

                        if dry:
                            self.stdout.write(f"[DRY] {path.name} -> Conta {conta.id} {data_saldo} = {valor:.2f}")
                            file_new += 1
                        else:
                            obj, created = Saldo.objects.update_or_create(
                                conta=conta, data=data_saldo, defaults={"valor": valor}
                            )
                            if created:
                                file_new += 1
                            else:
                                file_upd += 1

                else:
                    # ---------- TENTATIVA 3: SGML-lite (regex) ----------
                    tuples = _parse_sgml_ledgers(raw)
                    if not tuples:
                        self.stderr.write(self.style.ERROR(f"[{path.name}] Não foi possível extrair LEDGERBAL (SGML-lite)."))
                        total_warn += 1
                        continue

                    for acctid, bal_amt, bal_dt in tuples:
                        if not acctid or bal_amt is None or bal_dt is None:
                            file_warn += 1
                            continue
                        try:
                            data_saldo = _parse_ofx_date(bal_dt)
                        except Exception:
                            file_warn += 1
                            continue
                        conta, warn = _resolver_conta(acctid, None, agencia_prioritaria)
                        if warn:
                            self.stderr.write(self.style.WARNING(f"[{path.name}] {warn}"))
                            file_warn += 1
                        if not conta:
                            continue
                        try:
                            valor = round(float(str(bal_amt).replace(",", ".")), 2)
                        except Exception:
                            file_warn += 1
                            continue

                        if dry:
                            self.stdout.write(f"[DRY] {path.name} -> Conta {conta.id} {data_saldo} = {valor:.2f}")
                            file_new += 1
                        else:
                            obj, created = Saldo.objects.update_or_create(
                                conta=conta, data=data_saldo, defaults={"valor": valor}
                            )
                            if created:
                                file_new += 1
                            else:
                                file_upd += 1

            self.stdout.write(self.style.SUCCESS(
                f"[{path.name}] salvos={file_new} atualizados={file_upd} avisos={file_warn}"
            ))
            total_files += 1
            total_new += file_new
            total_upd += file_upd
            total_warn += file_warn

        resumo = f"Arquivos: {total_files} | Novos saldos: {total_new} | Atualizados: {total_upd} | Avisos: {total_warn}"
        if dry:
            self.stdout.write(self.style.WARNING("[DRY RUN] " + resumo))
        else:
            self.stdout.write(self.style.SUCCESS(resumo))
