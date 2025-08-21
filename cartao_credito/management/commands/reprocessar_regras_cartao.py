# cartao_credito/management/commands/reprocessar_regras_membro_cartao.py
from django.core.management.base import BaseCommand
from cartao_credito.models import Lancamento, RegraCartao
from cartao_credito.services.regras_membro import aplicar_regras_membro_se_vazio_lancamento

class Command(BaseCommand):
    help = "Aplica regras de membro do cartão APENAS em lançamentos sem membros."

    def add_arguments(self, parser):
        parser.add_argument(
            "--every", type=int, default=100,
            help="Imprime um heartbeat a cada N lançamentos processados (default: 100)."
        )
        parser.add_argument(
            "--chunk-size", type=int, default=1000,
            help="Tamanho do chunk do iterator do queryset (default: 1000)."
        )
        parser.add_argument(
            "--verbose", "-V", action="store_true",
            help="Mostra cada lançamento processado e a regra aplicada (se disponível)."
        )

    def handle(self, *args, **opts):
        every = max(int(opts.get("every") or 100), 1)
        chunk_size = max(int(opts.get("chunk_size") or 1000), 1)
        verbose = bool(opts.get("verbose"))

        regras_cache = list(
            RegraCartao.objects.filter(ativo=True)
            .order_by("prioridade", "nome")
            .prefetch_related("membros")
        )
        if not regras_cache:
            self.stdout.write(self.style.WARNING("⚠️  Nenhuma RegraCartao ativa encontrada. Nada a fazer."))
            return

        qs = (
            Lancamento.objects
            .filter(membros__isnull=True)
            .only("id", "descricao")   # suficiente p/ serviço
            .distinct()
        )

        total = 0
        aplicados = 0

        # Nem todo Django tem style.NOTICE; use write simples.
        self.stdout.write("▶ Iniciando reprocessamento de regras de membro (cartão)")
        self.stdout.write(f"   Regras em cache: {len(regras_cache)} | Heartbeat a cada {every} | chunk_size={chunk_size}")

        suporta_retornar_regra = True

        try:
            for lanc in qs.iterator(chunk_size=chunk_size):
                total += 1

                if suporta_retornar_regra:
                    try:
                        aplicou, regra = aplicar_regras_membro_se_vazio_lancamento(
                            lanc,
                            regras_cache=regras_cache,
                            retornar_regra=True
                        )
                    except TypeError:
                        # função não aceita retornar_regra -> fallback
                        suporta_retornar_regra = False
                        aplicou = aplicar_regras_membro_se_vazio_lancamento(lanc, regras_cache=regras_cache)
                        regra = None
                else:
                    aplicou = aplicar_regras_membro_se_vazio_lancamento(lanc, regras_cache=regras_cache)
                    regra = None

                if aplicou:
                    aplicados += 1
                    if verbose:
                        if regra is not None:
                            self.stdout.write(self.style.SUCCESS(f"✓ Aplicada: '{regra.nome}' -> lanc #{lanc.id}"))
                        else:
                            self.stdout.write(self.style.SUCCESS(f"✓ Aplicada em lanc #{lanc.id} (regra não disponível)"))
                else:
                    if verbose:
                        self.stdout.write(f"· Sem alteração: lanc #{lanc.id}")

                if not verbose and every and total % every == 0:
                    self.stdout.write(f"… {total} processados | {aplicados} com regra")

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n⏹ Interrompido pelo usuário."))

        self.stdout.write(self.style.SUCCESS(
            f"✅ Finalizado: {total} lançamentos verificados | {aplicados} receberam membros por regra"
        ))
