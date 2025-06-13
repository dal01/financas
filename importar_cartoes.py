import os
from ofxparse import OfxParser
from pathlib import Path
from django.utils.timezone import make_aware
from datetime import datetime

# Configure o Django
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from cartao_credito.models import Cartao, Fatura, Lancamento

BASE_DIR = Path(__file__).resolve().parent
pasta_base = BASE_DIR / "cartao_credito/data"

def importar_ofx(de_quem):
    pasta_usuario = pasta_base / de_quem
    print(f"🔍 Buscando arquivos em: {pasta_usuario.resolve()}")

    for caminho in pasta_usuario.glob("*.ofx"):
        print(f"📂 Importando: {caminho.name}")
        with open(caminho, "r", encoding="utf-8") as f:
            ofx = OfxParser.parse(f)

        for conta in ofx.accounts:
            # Criar ou obter cartão
            cartao, _ = Cartao.objects.get_or_create(nome=conta.number, titular=de_quem)
            print(f"💳 Cartão: {cartao.nome} – Titular: {cartao.titular}")

            for transacao in conta.statement.transactions:
                data = make_aware(transacao.date) if not transacao.date.tzinfo else transacao.date
                mes = data.month
                ano = data.year

                # Criar ou obter fatura
                fatura, _ = Fatura.objects.get_or_create(cartao=cartao, mes=mes, ano=ano)

                # Criar lançamento
                lancamento, criado = Lancamento.objects.get_or_create(
                    fatura=fatura,
                    data=data,
                    descricao=transacao.memo[:255],
                    valor=transacao.amount,
                )
                print(f" - {'Novo' if criado else 'Existente'}: {data.date()} | {transacao.memo[:40]} | R$ {transacao.amount:.2f}")

# 👇 Esse bloco precisa estar fora da função
if __name__ == "__main__":
    importar_ofx("dalton")
    importar_ofx("andrea")
