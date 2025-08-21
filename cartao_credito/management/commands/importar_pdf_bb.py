# cartao_credito/management/commands/importar_pdf_bb.py
from __future__ import annotations

import pathlib
from uuid import uuid4
from decimal import Decimal
from typing import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings

import pdfplumber

from cartao_credito.models import FaturaCartao, Lancamento
from cartao_credito.parsers.bb.dados_fatura import parse_dados_fatura
from cartao_credito.parsers.bb.lancamentos import parse_lancamentos


# ------------------ utils ------------------
def extrair_texto(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def style_header(stdout, title: str) -> str:
    try:
        return stdout.style.MIGRATE_HEADING(title)
    except Exception:
        return f"===== {title} ====="


def iter_pdfs(path: pathlib.Path) -> Iterable[pathlib.Path]:
    if path.is_file():
        yield path
    else:
        yield from sorted(path.rglob("*.pdf"))


# ------------------ command ------------------
class Command(BaseCommand):
    help = "Importa faturas do Banco do Brasil (PDF). Lê um arquivo único ou uma pasta (recursiva)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Caminho do PDF ou da pasta contendo PDFs")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Não grava no banco; apenas exibe o que seria importado",
        )
        parser.add_argument(
            "--debug-unmatched",
            action="store_true",
            help="Mostra blocos não reconhecidos nos lançamentos (amostra)",
        )
        parser.add_argument(
            "--debug-max",
            type=int,
            default=40,
            help="Máximo de blocos/linhas não casados a exibir por arquivo (padrão: 40)",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Se já houver fatura para (cartao_final, competência), apaga lançamentos e atualiza a fatura",
        )
        parser.add_argument(
            "--titular",
            type=str,
            default="",
            help="Força o titular a ser salvo na FaturaCartao (opcional)",
        )
        parser.add_argument(
            "--emissor",
            type=str,
            default="",
            help="Força o emissor a ser salvo na FaturaCartao (opcional)",
        )
        parser.add_argument(
            "--fonte",
            type=str,
            default="",
            help="Define a fonte_arquivo a salvar na fatura (por padrão usa o caminho do PDF)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Apaga a fatura existente (mesmo cartao_final + competência) antes de importar.",
        )
        parser.add_argument(
            "--force-all",
            action="store_true",
            help="(PERIGOSO) Apaga TODAS as faturas e lançamentos antes de processar os PDFs.",
        )

    def handle(self, *args, **opts):
        base_path = pathlib.Path(opts["path"])
        dry = opts["dry_run"]
        dbg = opts["debug_unmatched"]
        dbg_max = opts["debug_max"]
        force_replace = opts["replace"]
        titular_force = (opts.get("titular") or "").strip()
        emissor_force = (opts.get("emissor") or "").strip()
        fonte_force = (opts.get("fonte") or "").strip()
        force = opts["force"]
        force_all = opts["force_all"]

        # resolve relativo ao BASE_DIR se necessário
        if not base_path.exists():
            base2 = pathlib.Path(settings.BASE_DIR) / str(base_path)
            if base2.exists():
                base_path = base2

        if not base_path.exists():
            raise CommandError(f"Caminho inválido: {base_path} (cwd={pathlib.Path.cwd()})")

        pdfs = list(iter_pdfs(base_path))
        if not pdfs:
            self.stdout.write(self.style.WARNING(f"Nenhum PDF encontrado em {base_path}"))
            return

        if base_path.is_dir():
            self.stdout.write(self.style.NOTICE(f"Encontrados {len(pdfs)} PDFs em {base_path}"))

        # --force-all: limpa tudo antes de iniciar
        if force_all:
            self.stdout.write(self.style.WARNING("Apagando TODAS as faturas e lançamentos..."))
            try:
                # Se FK Lancamento->FaturaCartao for on_delete=CASCADE, isso remove também os lançamentos.
                FaturaCartao.objects.all().delete()
            except Exception:
                # fallback seguro, caso não seja CASCADE
                Lancamento.objects.all().delete()
                FaturaCartao.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Base limpa para reimportação."))

        ok = erros = ignorados = 0

        for pdf in pdfs:
            self.stdout.write(self.style.NOTICE(f"Processando {pdf}"))
            try:
                texto = extrair_texto(str(pdf))
                if not texto or len(texto.strip()) < 30:
                    self.stdout.write(self.style.WARNING(f"[{pdf}] Pouco texto extraído (talvez escaneado/OCR ausente)."))
                    continue

                # Etapa 1: dados gerais da fatura
                dados = parse_dados_fatura(texto, str(pdf))

                # Overrides opcionais de cabeçalho (em memória)
                if titular_force:
                    # titular é salvo na FaturaCartao; mantemos dados em memória inalterados
                    pass
                if emissor_force:
                    dados = dados.__class__(**{**dados.__dict__, "emissor": emissor_force})
                fonte_arquivo = fonte_force or str(pdf)

                # Etapa 2: lançamentos
                linhas = parse_lancamentos(texto, dados, debug_unmatched=dbg, debug_max=dbg_max)

                soma = sum((l.valor for l in linhas), Decimal("0"))
                total_str = f"{dados.total:.2f}" if dados.total is not None else "—"
                self.stdout.write(
                    f"[{pdf}] {len(linhas)} lançamentos | Soma capturada R$ {soma:.2f} | Total fatura PDF: {total_str}"
                )

                # Divergência (apenas aviso)
                if dados.total is not None and abs(soma - dados.total) > Decimal("0.05"):
                    self.stdout.write(
                        self.style.WARNING(
                            f"[AVISO] Divergência: soma capturada R$ {soma:.2f} ≠ total do PDF R$ {dados.total:.2f}"
                        )
                    )

                # Observações da etapa de dados_fatura
                for note in (dados.observacoes or []):
                    self.stdout.write(self.style.WARNING(f"[OBS] {note}"))

                if dry:
                    ok += 1
                    continue

                # --force: remove previamente a fatura alvo (e seus lançamentos)
                if force:
                    apagados = FaturaCartao.objects.filter(
                        cartao_final=dados.cartao_final,
                        competencia=dados.competencia,
                    ).delete()[0]
                    if apagados:
                        self.stdout.write(self.style.WARNING(
                            f"[{pdf}] --force: removida fatura existente (e lançamentos vinculados)."
                        ))

                with transaction.atomic():
                    # 1) localizar/criar fatura
                    fatura, created = FaturaCartao.objects.get_or_create(
                        cartao_final=dados.cartao_final,
                        competencia=dados.competencia,
                        defaults=dict(
                            emissor=(emissor_force or dados.emissor),
                            titular=(titular_force or ""),
                            bandeira=(dados.bandeira or ""),  # <-- grava bandeira ao criar
                            fechado_em=dados.fechado_em,
                            vencimento_em=dados.vencimento_em,
                            total=dados.total,
                            arquivo_hash=dados.arquivo_hash,
                            fonte_arquivo=fonte_arquivo,
                            import_batch=uuid4(),
                        ),
                    )

                    if not created and not force:
                        # Mesmo arquivo? (hash igual) e não pediu replace ⇒ ignorar
                        if fatura.arquivo_hash and fatura.arquivo_hash == dados.arquivo_hash and not force_replace:
                            ignorados += 1
                            self.stdout.write(self.style.SUCCESS(f"[{pdf}] Ignorado: fatura já importada (hash igual)."))
                            continue

                        # Se replace, apaga lançamentos e atualiza cabeçalho
                        if force_replace:
                            deleted = fatura.lancamentos.all().delete()[0]
                            self.stdout.write(self.style.WARNING(f"[{pdf}] Removidos {deleted} lançamentos existentes."))

                        # Atualiza cabeçalho (pode ter mudado)
                        fatura.emissor = (emissor_force or dados.emissor)
                        if titular_force:
                            fatura.titular = titular_force
                        # atualiza bandeira se parser trouxe (não sobrescreve com vazio)
                        if dados.bandeira:
                            fatura.bandeira = dados.bandeira
                        fatura.fechado_em = dados.fechado_em
                        fatura.vencimento_em = dados.vencimento_em
                        fatura.total = dados.total
                        fatura.arquivo_hash = dados.arquivo_hash
                        fatura.fonte_arquivo = fonte_arquivo
                        fatura.save()

                    # 2) grava lançamentos vinculados à fatura
                    to_create = [
                        Lancamento(
                            fatura=fatura,
                            data=l.data,
                            descricao=l.descricao,
                            cidade=l.cidade or "",
                            pais=l.pais or "",
                            secao=l.secao,
                            valor=l.valor,
                            moeda=None,
                            valor_moeda=None,
                            taxa_cambio=None,
                            etiqueta_parcela=l.etiqueta_parcela,
                            parcela_num=l.parcela_num,
                            parcela_total=l.parcela_total,
                            observacoes=None,
                            hash_linha=l.hash_linha,
                            hash_ordem=l.hash_ordem,
                            is_duplicado=l.is_duplicado,
                            fitid=None,
                        )
                        for l in linhas
                    ]
                    Lancamento.objects.bulk_create(to_create, batch_size=500)

                ok += 1
                self.stdout.write(self.style.SUCCESS(f"[{pdf}] Importação concluída ({len(linhas)} lançamentos)."))

            except ValueError as e:
                erros += 1
                self.stderr.write(self.style.ERROR(f"[{pdf}] ERRO (parse): {e}"))
            except Exception as e:
                erros += 1
                self.stderr.write(self.style.ERROR(f"[{pdf}] ERRO inesperado: {e}"))

        # Resumo
        self.stdout.write("")
        self.stdout.write(style_header(self.stdout, "Resumo"))
        self.stdout.write(f"  PDFs processados : {len(pdfs)}")
        self.stdout.write(f"  Importados       : {ok}")
        self.stdout.write(f"  Ignorados        : {ignorados}")
        self.stdout.write(f"  Com erro         : {erros}")
