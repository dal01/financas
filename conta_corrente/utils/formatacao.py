import re

def formatar_descricao_transacao(name: str = "", memo: str = "", descricao_completa: str = "") -> str:
    """
    Formata descrições de transações para o padrão: favorecido/estabelecimento - tipo
    
    Args:
        name: Campo NAME do OFX ou parte inicial da descrição
        memo: Campo MEMO do OFX ou parte final da descrição  
        descricao_completa: Descrição já montada (formato antigo) para correção
        
    Returns:
        Descrição formatada no padrão: "favorecido - tipo"
    """
    
    # Se foi passada uma descrição completa (para correção), analisa ela
    if descricao_completa:
        return _corrigir_descricao_existente(descricao_completa)
    
    # Se foram passados name e memo (para importação OFX), monta a descrição
    return _montar_descricao_ofx(name, memo)


def _montar_descricao_ofx(name: str, memo: str) -> str:
    """Monta descrição a partir dos campos NAME e MEMO do OFX"""
    name = str(name or "").strip()
    memo = str(memo or "").strip()
    
    # Tratamento especial para PIX
    if name and "pix" in name.lower():
        if memo:
            # memo formato: "20/05 17:06 Moises Rodrigues De Olivei"
            partes_memo = memo.split(' ', 2)
            if len(partes_memo) >= 3:
                favorecido = partes_memo[2]  # "Moises Rodrigues De Olivei"
                tipo = name  # "Pix - Enviado"
                return f"{favorecido} - {tipo}"
    
    # Para outros tipos, monta descrição padrão e depois reformata
    if name and memo and memo != name:
        descricao_temp = f"{name} -- {memo}"
        return _corrigir_descricao_existente(descricao_temp)
    elif name:
        return name
    elif memo:
        return memo
    
    return ""


def _corrigir_descricao_existente(descricao: str) -> str:
    """Corrige descrições já existentes no formato antigo"""
    
    # 1. PIX: "pix - enviado -- 20/05 17:06 moises rodrigues de olivei"
    match = re.match(r'^(pix.*?)\s*--\s*\d{2}/\d{2}\s+\d{2}:\d{2}\s+(.+)$', descricao, re.IGNORECASE)
    if match:
        tipo = match.group(1).strip()
        favorecido = match.group(2).strip()
        return f"{favorecido} - {tipo}"
    
    # 2. PIX Agendado: "pix agendado recorrente -- 08/09 ab soul sports 002/999"
    match = re.match(r'^(pix.*?)\s*--\s*\d{2}/\d{2}\s+(.+?)(?:\s+\d{3}/\d{3}.*)?$', descricao, re.IGNORECASE)
    if match:
        tipo = match.group(1).strip()
        favorecido = match.group(2).strip()
        return f"{favorecido} - {tipo}"
    
    # 3. Pagamento: "pagamento de boleto -- paris saint germain academy brasilia"
    match = re.match(r'^(pagamento.*?)\s*--\s*(.+)$', descricao, re.IGNORECASE)
    if match:
        tipo = match.group(1).strip()
        favorecido = match.group(2).strip()
        return f"{favorecido} - {tipo}"
    
    # 4. TED: "ted transf.eletr.disponiv -- 033 4551 15757629860 milton m 090/999m"
    match = re.match(r'^(ted.*?)\s*--\s*(?:\d+\s+)*(.+?)(?:\s+\d+/\d+.*)?$', descricao, re.IGNORECASE)
    if match:
        tipo = match.group(1).strip()
        favorecido = match.group(2).strip()
        # Remove números que parecem ser agência/conta
        favorecido = re.sub(r'\s+\d{3,}.*$', '', favorecido).strip()
        return f"{favorecido} - {tipo}"
    
    # 5. Compra: "compra com cartao -- 04/07 13:20 concebra"
    match = re.match(r'^(compra.*?)\s*--\s*\d{2}/\d{2}\s+\d{2}:\d{2}\s+(.+)$', descricao, re.IGNORECASE)
    if match:
        tipo = match.group(1).strip()
        estabelecimento = match.group(2).strip()
        return f"{estabelecimento} - {tipo}"
    
    # 6. Formato genérico: "tipo -- detalhes"
    match = re.match(r'^(.+?)\s*--\s*(.+)$', descricao)
    if match:
        tipo = match.group(1).strip()
        detalhes = match.group(2).strip()
        # Remove data/hora do início
        detalhes = re.sub(r'^\d{2}/\d{2}\s+\d{2}:\d{2}\s+', '', detalhes)
        # Remove códigos numéricos do final
        detalhes = re.sub(r'\s+\d{3}/\d{3}.*$', '', detalhes)
        return f"{detalhes} - {tipo}"
    
    # Se não conseguir identificar padrão, retorna original
    return descricao