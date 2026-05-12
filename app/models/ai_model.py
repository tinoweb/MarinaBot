import os
from openai import OpenAI
from dotenv import load_dotenv

# Carrega as variáveis de ambiente
load_dotenv()

# Instância global do cliente OpenAI (SDK v1.x)
_openai_client = None

def _get_openai_client():
    """Retorna o cliente OpenAI inicializado."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada no .env")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def _get_system_prompt():
    """
    Retorna o prompt do sistema. Tenta carregar do banco de dados (tabela ai_settings),
    senão usa o padrão hardcoded.
    """
    try:
        from app.config.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT setting_value FROM ai_settings WHERE setting_key = 'system_prompt' LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row.get('setting_value'):
            return row['setting_value']
    except Exception:
        pass
    # Prompt padrão
    return (
        "Você é um assistente virtual útil e profissional. "
        "Seu objetivo é ajudar os clientes de forma cordial e eficiente. "
        "Seja cordial, profissional e preciso. "
        "Responda sempre em português."
    )


def _get_ai_setting(key, default=None):
    """
    Retorna uma configuração da IA do banco de dados.
    """
    try:
        from app.config.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT setting_value FROM ai_settings WHERE setting_key = '{key}' LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row.get('setting_value'):
            return row['setting_value']
    except Exception:
        pass
    return default


def get_ai_response(chat_session):
    """
    Obtém uma resposta da IA com base no histórico da conversa.

    Args:
        chat_session (ChatSession): Sessão de chat atual

    Returns:
        str: Resposta gerada pela IA
    """
    try:
        # Carrega configurações do banco
        bot_name = _get_ai_setting('bot_name', 'AtendBot')
        welcome_message = _get_ai_setting('welcome_message', 'Olá! Como posso ajudar você hoje?')
        ai_model = _get_ai_setting('ai_model', 'gpt-3.5-turbo')
        temperature_str = _get_ai_setting('temperature', '0.7')

        # Converte temperatura para float
        try:
            temperature = float(temperature_str)
        except:
            temperature = 0.7

        # Obtém o histórico de conversa formatado
        messages = chat_session.get_conversation_history()

        # Verifica se é a primeira mensagem do usuário
        user_messages = [m for m in chat_session.messages if m.get('role') == 'user']
        if len(user_messages) == 1:
            # Mensagem de boas-vindas na primeira interação
            return welcome_message

        # Adiciona o system prompt se não estiver presente
        system_prompt = _get_system_prompt()
        if messages and messages[0].get('role') != 'system':
            messages.insert(0, {'role': 'system', 'content': system_prompt})

        # Faz a chamada para a API da OpenAI (SDK v1.x)
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=ai_model,
            messages=messages,
            max_tokens=500,
            temperature=temperature
        )

        # Extrai a resposta
        ai_response = response.choices[0].message.content

        # Verifica se a resposta contém informações que precisamos coletar
        _update_user_data_from_response(chat_session, ai_response)

        return ai_response

    except Exception as e:
        print(f"[AI] Erro ao obter resposta da IA: {e}")
        import traceback
        traceback.print_exc()
        return "Desculpe, estou enfrentando alguns problemas técnicos. Por favor, tente novamente em instantes."


def _update_user_data_from_response(chat_session, response):
    """
    Extrai e atualiza dados do usuário a partir da resposta da IA.

    Args:
        chat_session (ChatSession): Sessão de chat atual
        response (str): Resposta da IA
    """
    response_lower = response.lower()

    # Detectar menção a data de admissão
    if "data de admissão" in response_lower and "data_admissao" not in chat_session.user_data:
        chat_session.update_user_data("esperando_data_admissao", "true")

    # Detectar menção a salário
    if "salário" in response_lower and "salario" not in chat_session.user_data:
        chat_session.update_user_data("esperando_salario", "true")


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

    # Extrair nome completo (se ainda não tiver)
    if not user_data.get('nome_completo'):
        # Padrão: "meu nome é X", "sou X", "eu me chamo X"
        nome_patterns = [
            r'meu nome (?:é|e) ([a-zA-Z\s]+)',
            r'eu (?:me |sou )?(?:chamo|sou) ([a-zA-Z\s]+)',
            r'sou ([a-zA-Z\s]+)'
        ]
        for pattern in nome_patterns:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if match:
                nome = match.group(1).strip()
                if len(nome) > 2 and len(nome.split()) >= 2:  # Pelo menos nome e sobrenome
                    chat_session.update_user_data('nome_completo', nome)
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
