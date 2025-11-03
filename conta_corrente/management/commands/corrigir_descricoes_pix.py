from django.core.management.base import BaseCommand
from conta_corrente.models import Transacao
from conta_corrente.utils.formatacao import formatar_descricao_transacao

class Command(BaseCommand):
    help = "Corrige as descrições de transações existentes no banco de dados"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Apenas simula as alterações")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Busca todas as transações com formato antigo
        transacoes = Transacao.objects.filter(descricao__contains=' -- ')
        
        total = transacoes.count()
        atualizadas = 0
        
        self.stdout.write(f"Encontradas {total} transações para analisar")
        
        for tx in transacoes:
            descricao_antiga = tx.descricao
            nova_descricao = formatar_descricao_transacao(descricao_completa=descricao_antiga)
            
            if nova_descricao != descricao_antiga:
                if not dry_run:
                    tx.descricao = nova_descricao
                    tx.save(update_fields=['descricao'])
                
                atualizadas += 1
                self.stdout.write(f"  {tx.id}: '{descricao_antiga}' → '{nova_descricao}'")
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: {atualizadas} transações seriam atualizadas"))
        else:
            self.stdout.write(self.style.SUCCESS(f"✅ {atualizadas} transações atualizadas com sucesso"))