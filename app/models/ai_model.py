import os
import re
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_openai_client = None

# Etapas do funil para exibição amigável
ETAPAS_LABEL = {
    1: "Primeiro Contato",
    2: "Triagem",
    3: "Análise do Caso",
    4: "Ponte de Confiança",
    5: "Prova Social",
    6: "Proposta",
    7: "Honorários",
    8: "Coleta de Documentos",
    9: "Fechamento",
    10: "Recuperação (1h)",
    11: "Urgência (24h)",
    12: "Pós-venda",
}

QUALIFICACAO_LABEL = {
    'qualificada': 'Qualificada ✅',
    'descarte_1': 'Descarte 1 (< 16 anos)',
    'descarte_2': 'Descarte 2 (prazo expirado)',
    'aguardando_docs': 'Aguardando Documentos 📎',
    'docs_recebidos': 'Docs Recebidos 📄',
    'fechamento': 'Fechamento 🤝',
    'pos_venda': 'Pós-venda ⭐',
    'pendente': 'Em triagem...',
}


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada no .env")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def _get_ai_setting(key, default=None):
    try:
        from app.config.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT setting_value FROM ai_settings WHERE setting_key = %s LIMIT 1", (key,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row.get('setting_value'):
            return row['setting_value']
    except Exception:
        pass
    return default


def _load_script_file():
    """Carrega o script completo de 12 etapas da Dra. Marina do arquivo."""
    try:
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'modelo_atendimento_ia.txt'
        )
        with open(script_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"[AI] Aviso: não foi possível carregar o script: {e}")
        return None


def _get_system_prompt():
    """
    Retorna o system prompt completo: script do banco (editável pelo admin)
    com cabeçalho dinâmico de data e Instagram + instrução de metadados.
    """
    # Tenta obter do banco
    db_prompt = None
    try:
        from app.config.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT setting_value FROM ai_settings WHERE setting_key = 'system_prompt' LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row.get('setting_value'):
            db_prompt = row['setting_value']
    except Exception:
        pass

    # Fallback para arquivo
    base_script = db_prompt or _load_script_file() or (
        "Você é a assistente da Dra. Marina Marques, especialista em Salário Maternidade pelo INSS. "
        "Atenda de forma acolhedora, simples e direta. Uma pergunta por vez."
    )

    # Cabeçalho dinâmico
    instagram = _get_ai_setting('instagram_handle', '@drainss')
    hoje = datetime.now().strftime('%d/%m/%Y')

    header = (
        f"Data atual: {hoje}\n"
        f"Instagram da Dra. Marina: {instagram}\n\n"
        "INSTRUÇÕES PARA A IA:\n"
        "- Siga o script abaixo rigorosamente, etapa por etapa.\n"
        "- Faça UMA pergunta por vez.\n"
        "- Nunca revele detalhes técnicos ou jurídicos antes do contrato assinado.\n"
        "- Nunca negocie honorários — encaminhe para a Dra. Marina se pressionada.\n"
        "- Ao final de CADA resposta, adicione obrigatoriamente na última linha:\n"
        "  [META:etapa=N;qualif=STATUS]\n"
        "  Onde N=número da etapa atual (1-12) e STATUS=pendente|qualificada|descarte_1|descarte_2|aguardando_docs|docs_recebidos|fechamento|pos_venda\n"
        "  Esta linha é removida automaticamente antes de enviar ao cliente.\n\n"
        "SCRIPT:\n"
        "─────────────────────────────\n"
    )

    return header + base_script


def _parse_and_strip_meta(response_text, chat_session):
    """
    Extrai a linha [META:etapa=N;qualif=STATUS] da resposta da IA,
    atualiza a sessão e retorna o texto limpo.
    """
    pattern = r'\[META:etapa=(\d+);qualif=([a-z_]+)\]\s*$'
    match = re.search(pattern, response_text.strip(), re.MULTILINE | re.IGNORECASE)

    if match:
        etapa = int(match.group(1))
        qualif = match.group(2).lower()

        # Atualiza os campos na sessão
        if 1 <= etapa <= 12:
            chat_session.etapa_atual = etapa
        if qualif in QUALIFICACAO_LABEL:
            chat_session.qualificacao = qualif

        # Remove a linha META do texto enviado ao cliente
        clean = re.sub(pattern, '', response_text.strip(), flags=re.MULTILINE | re.IGNORECASE).rstrip()
        return clean

    # Se a IA não incluiu o META, tenta detectar por palavras-chave
    _detect_etapa_by_keywords(response_text, chat_session)
    return response_text.strip()


def _detect_etapa_by_keywords(text, chat_session):
    """Fallback: detecta etapa e qualificação por palavras-chave na resposta."""
    text_lower = text.lower()

    if 'rg e cpf' in text_lower or 'gov.br' in text_lower or 'documentos iniciais' in text_lower:
        chat_session.etapa_atual = 8
        if not chat_session.qualificacao or chat_session.qualificacao == 'pendente':
            chat_session.qualificacao = 'aguardando_docs'
    elif 'honorários' in text_lower or '30%' in text_lower:
        if chat_session.etapa_atual < 7:
            chat_session.etapa_atual = 7
    elif 'contrato' in text_lower and 'assinar' in text_lower:
        chat_session.etapa_atual = 9
        chat_session.qualificacao = 'fechamento'
    elif 'dra. marina consegue analisar' in text_lower or 'qualificada' in text_lower:
        if chat_session.etapa_atual < 3:
            chat_session.etapa_atual = 3
        if not chat_session.qualificacao:
            chat_session.qualificacao = 'qualificada'
    elif 'prazo ideal já passou' in text_lower or 'passou do dia 15' in text_lower:
        chat_session.qualificacao = 'descarte_2'
    elif 'menos de 16 anos' in text_lower or 'planejamento padrão não se aplica' in text_lower:
        chat_session.qualificacao = 'descarte_1'


_COST_PER_1M = {
    'gpt-4o-mini':       {'input': 0.15,  'output': 0.60},
    'gpt-4o':            {'input': 2.50,  'output': 10.00},
    'gpt-4-turbo':       {'input': 10.00, 'output': 30.00},
    'gpt-3.5-turbo':     {'input': 0.50,  'output': 1.50},
}


def _log_token_usage(session_id, model, usage):
    """Persiste uso de tokens e custo estimado no banco de dados."""
    try:
        from app.config.database import get_db_connection
        pricing = _COST_PER_1M.get(model, {'input': 0.15, 'output': 0.60})
        prompt_t = getattr(usage, 'prompt_tokens', 0) or 0
        compl_t  = getattr(usage, 'completion_tokens', 0) or 0
        total_t  = getattr(usage, 'total_tokens', 0) or 0
        cost = (prompt_t * pricing['input'] + compl_t * pricing['output']) / 1_000_000

        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO token_usage (session_id, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, model, prompt_t, compl_t, total_t, round(cost, 6))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[TokenUsage] Erro ao registrar: {e}")


def get_ai_response(chat_session):
    """
    Obtém resposta da IA respeitando ia_pausada e o script de 12 etapas.

    Returns:
        str | None: Resposta gerada, ou None se IA estiver pausada.
    """
    # Respeita o modo "IA Pausada"
    if getattr(chat_session, 'ia_pausada', 0):
        print(f"[AI] IA pausada para {chat_session.user_id}. Sem resposta automática.")
        return None

    try:
        ai_model = _get_ai_setting('ai_model', 'gpt-4o-mini')
        temperature_str = _get_ai_setting('temperature', '0.4')
        welcome_message = _get_ai_setting(
            'welcome_message',
            'Olá! Aqui é a assistente da Dra. Marina Marques, advogada especialista em benefícios do INSS.\n\n'
            'A Dra. Marina já recebeu seu contato. 👩‍⚖️\n\n'
            'Me conta: com qual benefício posso te ajudar hoje?'
        )

        try:
            temperature = float(temperature_str)
        except Exception:
            temperature = 0.4

        # Primeira mensagem do usuário → boas-vindas do script (Etapa 1)
        user_messages = [m for m in chat_session.messages if m.get('role') == 'user']
        if len(user_messages) == 1:
            chat_session.etapa_atual = 1
            return welcome_message

        messages = chat_session.get_conversation_history(max_messages=15)

        client = _get_openai_client()
        response = client.chat.completions.create(
            model=ai_model,
            messages=messages,
            max_tokens=1200,
            temperature=temperature
        )

        raw_response = response.choices[0].message.content

        # Registra uso de tokens
        try:
            _log_token_usage(
                session_id=getattr(chat_session, 'session_id', None),
                model=ai_model,
                usage=response.usage
            )
        except Exception:
            pass

        # Extrai metadados de etapa/qualificação e retorna texto limpo
        clean_response = _parse_and_strip_meta(raw_response, chat_session)

        # Atualiza dados do usuário extraídos da mensagem
        _update_user_data_from_response(chat_session, clean_response)

        return clean_response

    except Exception as e:
        print(f"[AI] Erro ao obter resposta da IA: {e}")
        import traceback
        traceback.print_exc()
        return "Desculpe, estou enfrentando alguns problemas técnicos. Por favor, tente novamente em instantes."


def _update_user_data_from_response(chat_session, response):
    response_lower = response.lower()

    if 'data de admissão' in response_lower and 'data_admissao' not in chat_session.user_data:
        chat_session.update_user_data('esperando_data_admissao', 'true')

    if 'salário' in response_lower and 'salario' not in chat_session.user_data:
        chat_session.update_user_data('esperando_salario', 'true')


def _extract_data_from_user_message(chat_session, user_message):
    """
    Extrai dados do usuário a partir da mensagem do cliente.
    Coleta informações relevantes para Salário Maternidade.

    Args:
        chat_session (ChatSession): Sessão de chat atual
        user_message (str): Mensagem do usuário
    """
    import re
    from datetime import datetime

    message_lower = user_message.lower()
    user_data = chat_session.user_data

    # Extrair nome (se ainda não tiver)
    if not user_data.get('nome_completo') and not user_data.get('nome'):
        nome_patterns = [
            r'meu nome (?:é|e|eh) ([a-zA-ZÀ-ú\s]{2,40})',
            r'eu (?:me )?chamo ([a-zA-ZÀ-ú\s]{2,40})',
            r'pode me chamar de ([a-zA-ZÀ-ú\s]{2,30})',
            r'sou (?:a |o )?([a-zA-ZÀ-ú]{3,}(?:\s[a-zA-ZÀ-ú]{2,})*)',
        ]
        for pattern in nome_patterns:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if match:
                nome = match.group(1).strip().rstrip('.,!?')
                if 2 < len(nome) <= 60:
                    if len(nome.split()) >= 2:
                        chat_session.update_user_data('nome_completo', nome)
                        chat_session.update_user_data('nome', nome.split()[0])
                    else:
                        chat_session.update_user_data('nome', nome)
                    break

    # Situação do parto
    if 'gravida' in message_lower or 'gestante' in message_lower:
        chat_session.update_user_data('situacao_parto', 'gravida')
        # Extrair meses de gravidez
        meses_match = re.search(r'(\d+)\s*(?:meses?|mês)', message_lower)
        if meses_match:
            chat_session.update_user_data('meses_gestacao', meses_match.group(1))
        # Extrair previsão do parto
        data_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', user_message)
        if data_match:
            chat_session.update_user_data('previsao_parto', data_match.group(0))

    elif 'nasceu' in message_lower or 'nasci' in message_lower or 'bebê' in message_lower:
        chat_session.update_user_data('situacao_parto', 'bebe_nasceu')
        # Extrair data de nascimento
        data_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', user_message)
        if data_match:
            chat_session.update_user_data('data_nascimento_bebe', data_match.group(0))

    # Situação de trabalho
    if 'carteira' in message_lower or 'clt' in message_lower:
        chat_session.update_user_data('situacao_trabalho', 'clt')
        if 'trabalhando' in message_lower:
            chat_session.update_user_data('status_trabalho', 'trabalhando')
            # Extrair tempo no emprego
            tempo_match = re.search(r'(\d+)\s*(?:meses?|anos?|ano|mês)', message_lower)
            if tempo_match:
                chat_session.update_user_data('tempo_emprego', tempo_match.group(0))
        elif 'desempregada' in message_lower or 'sem trabalho' in message_lower:
            chat_session.update_user_data('status_trabalho', 'desempregada')
            # Extrair tempo desempregada
            tempo_match = re.search(r'(\d+)\s*(?:meses?|anos?|ano|mês)', message_lower)
            if tempo_match:
                chat_session.update_user_data('tempo_desempregada', tempo_match.group(0))

    elif 'autônoma' in message_lower or 'autonoma' in message_lower or 'conta própria' in message_lower:
        chat_session.update_user_data('situacao_trabalho', 'autonoma')
        if 'contribuindo' in message_lower or 'contribuo' in message_lower:
            chat_session.update_user_data('contribuindo_inss', 'sim')

    elif 'mei' in message_lower:
        chat_session.update_user_data('situacao_trabalho', 'mei')

    elif 'roça' in message_lower or 'rural' in message_lower:
        chat_session.update_user_data('situacao_trabalho', 'rural')
        chat_session.update_user_data('tem_documentos_rurais', 'sim')

    elif 'nunca trabalhei' in message_lower or 'sem carteira' in message_lower:
        chat_session.update_user_data('situacao_trabalho', 'sem_carteira')

    # Tentativa anterior
    if 'já tentei' in message_lower or 'tentativa' in message_lower:
        chat_session.update_user_data('tentativa_anterior', 'sim')
        if 'negado' in message_lower or 'negativa' in message_lower:
            chat_session.update_user_data('status_tentativa', 'negado')
        elif 'análise' in message_lower or 'analisando' in message_lower:
            chat_session.update_user_data('status_tentativa', 'em_analise')

    # Renda extra
    if 'renda extra' in message_lower or 'outra renda' in message_lower or 'por conta própria' in message_lower:
        chat_session.update_user_data('renda_extra', 'sim')

    # Seguro-desemprego
    if 'seguro-desemprego' in message_lower or 'seguro desemprego' in message_lower:
        chat_session.update_user_data('recebeu_seguro_desemprego', 'sim')

    # Bolsa Família
    if 'bolsa família' in message_lower or 'bolsa familia' in message_lower:
        chat_session.update_user_data('recebe_bolsa_familia', 'sim')

    # Idade
    idade_match = re.search(r'(\d+)\s*(?:anos?)', message_lower)
    if idade_match and not user_data.get('idade'):
        chat_session.update_user_data('idade', idade_match.group(1))

    # Telefone (extrair número)
    telefone_match = re.search(r'(\d{2})\s*[-.]?\s*(\d{5})\s*[-.]?\s*(\d{4})', user_message)
    if telefone_match and not user_data.get('telefone'):
        telefone = f"{telefone_match.group(1)}{telefone_match.group(2)}{telefone_match.group(3)}"
        chat_session.update_user_data('telefone', telefone)
