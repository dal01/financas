# Anotações do Projeto

## Pendências
- [ ] Implementar conversão de moedas no importador de OFX.
- [ ] Revisar regra de categorização automática (descrição no OFX).
- [ ] Criar link no resumo para abrir transações filtradas por mês.
- [ ] Ajustar template de transações (renderização parou depois de última alteração).

## Decisões Técnicas
- **Importador de cartões**: atualmente NÃO converte valores de moedas estrangeiras para BRL.
- **Filtro de mês**: a view de transações já suporta `mes` e `ano` como parâmetros GET.
- **Admin**: `LancamentoAdmin` exibe `data`, `descricao`, `valor`, `fatura`; filtro por `fatura__cartao`.

## Ideias Futuras
- Criar tela no Django Admin para editar taxa de câmbio manualmente.
- Permitir importar CSV além do OFX.
- Criar dashboard com gráficos (gastos por categoria e evolução mensal).


## problemas detectados
- compras parceladas só aparecem depois que a parcela caiu, ou seja, o gasto do mês nunca é real até que caiam todas parcelas

##
criar instituicao financeira
  Estou usando como codigo duas letras (BB, CX)
python manage.py importar_ofx bb conta_corrente/data/

## para mudar de dev para prod
.env
AMBIENTE=dev