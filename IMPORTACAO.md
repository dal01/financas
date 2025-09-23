# Guia de Importação de Dados

Este arquivo contém exemplos de comandos para importar dados financeiros para o sistema.

---

## 1. Importar dados do cartão de crédito (PDF Banco do Brasil)

**Dalton:**
```sh
python manage.py importar_pdf_cartao_bb f:\sistemas\financas\data\cartao_bb\dalton --titular dalton
```

**Andrea:**
```sh
python manage.py importar_pdf_cartao_bb f:\sistemas\financas\data\cartao_bb\andrea --titular andrea
```

- Substitua o caminho pelo diretório ou arquivo PDF desejado.
- Use `--titular` para informar o nome do titular do cartão.

---

## 2. Importar dados da conta corrente (OFX)

**Dalton:**
```sh
python manage.py importar_ofx f:\sistemas\financas\data\conta_corrente\dalton\2025
```

**Andrea:**
```sh
python manage.py importar_ofx f:\sistemas\financas\data\conta_corrente\andrea\2025
```

- O primeiro argumento (`bb`) é o nome da instituição.
- O segundo argumento é o diretório onde estão os arquivos `.ofx`.

**rodar as regras de ocultacao depois da importacao**
```sh
python manage.py aplicar_regras_ocultacao

```

## 3. Importar apenas saldos da conta corrente (OFX)

**Dalton:**
```sh
python manage.py importar_saldos_ofx --dir f:\sistemas\financas\data\conta_corrente\dalton\bb
```

**Andrea:**
```sh
python manage.py importar_saldos_ofx --dir f:\sistemas\financas\data\conta_corrente\andrea\bb
```

- Use este comando se quiser importar apenas os saldos diários dos arquivos OFX.

---

## Observações

- Execute os comandos no terminal, dentro do ambiente virtual do projeto.
- Certifique-se de que os arquivos estejam no local correto e com permissão de leitura.
- Consulte os parâmetros adicionais de cada comando usando `--help`, por exemplo:

```sh
python manage.py importar_pdf_cartao_bb --help
python manage.py importar_ofx --help
python manage.py importar_saldos_ofx --help
```

```sh
.\venv\Scripts\activate
python manage.py runserver
```