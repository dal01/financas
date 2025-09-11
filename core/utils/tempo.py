from datetime import date, datetime

def periodo_padrao() -> tuple[str, str]:
    hoje = date.today()
    data_ini = date(hoje.year, 1, 1).strftime("%Y-%m-%d")
    data_fim = hoje.strftime("%Y-%m-%d")
    return data_ini, data_fim

def valida_data(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def str_para_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None