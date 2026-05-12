from flask import Blueprint, request, jsonify
from app.models.chat_model import ChatSession
from app.models.ai_model import get_ai_response
from app.models.whatsapp_model import WhatsAppConfig
import re

webhook_bp = Blueprint('webhook', __name__)


@webhook_bp.route('/webhook/wppconnect', methods=['POST'])
def wppconnect_webhook():
    """Recebe todos os eventos enviados pelo WPP Connect Server."""
    print(f"[Webhook] Webhook chamado! Headers: {dict(request.headers)}")
    
    data = request.get_json(silent=True) or {}
    event = data.get('event', '')
    session = data.get('session', '')
    
    print(f"[Webhook] Evento recebido: {event} (Sessão: {session})")
    print(f"[Webhook] Payload completo: {data}")
    
    # Log para depuração
    if event != 'qrReadSuccess': # Evita flood se for apenas QR polling
        print(f"[Webhook] Evento recebido: {event} (Sessão: {session})")

    if event == 'onConnected':
        phone = data.get('phone', '')
        WhatsAppConfig.save_config(
            session_name=session,
            phone_number=phone,
            status='connected'
        )
        print(f"[Webhook] Sessão '{session}' conectada. Telefone: {phone}")
        return jsonify({'status': 'ok'})

    if event in ('onDisconnected', 'qrReadFail', 'sessionExpired', 'browserClose'):
        WhatsAppConfig.save_config(session_name=session, status='disconnected')
        print(f"[Webhook] Sessão '{session}' desconectada. Evento: {event}")
        return jsonify({'status': 'ok'})

    if event.lower() in ('onmessage', 'message'):
        # WPP Connect envia a mensagem diretamente no payload, não dentro de 'message'
        message = data if data.get('content') or data.get('body') else data.get('message', {})
        # Ignora mensagens enviadas pelo próprio bot para evitar loop
        if message.get('fromMe'):
            print(f"[Webhook] Mensagem própria (fromMe=True) ignorada.")
            return jsonify({'status': 'ok', 'note': 'fromMe ignored'})
        _handle_incoming_message(session, message)
        return jsonify({'status': 'ok'})

    return jsonify({'status': 'ignored', 'event': event})


def _normalize_phone(phone_str):
    """Extrai apenas os números e formata como @c.us"""
    if not phone_str:
        return None
    
    # Procura por padrões de número de telefone específicos
    # Formatos: +55 XX XXXXX-XXXX, 55 XX XXXXX-XXXX, (55) XX XXXXX-XXXX
    phone_patterns = [
        r'\+?(\d{2}\s?\d{2}\s?\d{4,5}[-\s]?\d{4})',  # +55 XX XXXXX-XXXX
        r'(\d{10,11})',  # Apenas 10-11 dígitos consecutivos
        r'\((\d{2})\)\s*(\d{4,5}[-\s]?\d{4})',  # (55) XXXXX-XXXX
    ]
    
    for pattern in phone_patterns:
        match = re.search(pattern, phone_str)
        if match:
            # Para o padrão com parênteses, precisamos juntar os grupos
            if '(' in pattern:
                groups = match.groups()
                digits = ''.join(filter(None, groups))
            else:
                digits = match.group(1)
            
            # Validação: deve ter entre 10 e 15 dígitos (DDD + número)
            if 10 <= len(digits) <= 15:
                # Garante que comece com código do país se não tiver
                if len(digits) == 10:  # Apenas número sem DDD
                    digits = '55' + digits  # Assume Brasil
                elif len(digits) == 11 and digits.startswith('0'):  # 0XX XXXXXXXX
                    digits = digits[1:]  # Remove o zero inicial
                
                print(f"[Webhook] Telefone extraído: {phone_str} -> {digits}@c.us")
                return f"{digits}@c.us"
    
    # Fallback: remove tudo que não for dígito (com validação mais rigorosa)
    digits = re.sub(r'\D', '', phone_str)
    if digits and 10 <= len(digits) <= 15:
        print(f"[Webhook] Telefone extraído (fallback): {phone_str} -> {digits}@c.us")
        return f"{digits}@c.us"
    
    print(f"[Webhook] Não foi possível extrair telefone válido de: {phone_str}")
    return None


def _handle_incoming_message(session, message):
    """Processa mensagem recebida e responde com IA via WPP Connect."""
    sender_id = message.get('from') or message.get('chatId')
    message_id = message.get('id') or message.get('msgId')
    # Extrai o texto da mensagem (suporta body, caption, text e content)
    text = (
        message.get('content') or
        message.get('body') or
        message.get('caption') or
        message.get('text') or ''
    ).strip()

    print(f"[Webhook] Processando mensagem de {sender_id}: '{text[:80]}'")

    # Ignora mensagens de grupo
    if message.get('isGroupMsg') or message.get('isGroup'):
        print(f"[Webhook] Mensagem de grupo ignorada.")
        return

    # Ignora mensagens sem remetente ou sem texto
    if not sender_id or not text:
        print(f"[Webhook] Mensagem ignorada: sender_id={sender_id!r}, text={text!r}")
        return

    # Ignora números de status (@broadcast) e newsletter
    if '@broadcast' in sender_id or 'newsletter' in sender_id:
        return

    try:
        from app.services.whatsapp_service import get_wpp_service
        wpp = get_wpp_service()

        chat_session = ChatSession(sender_id)
        
        # 1. Salva o message_id para futuros envios de send-reply
        if message_id:
            chat_session.update_user_data('last_message_id', message_id)

        # 2. Tenta obter o número real para salvar como metadado
        # Prioridade 1: Já temos no banco?
        real_phone = chat_session.user_data.get('real_phone')
        
        if not real_phone:
            sender = message.get('sender', {})
            # Prioridade 2: formattedName no payload (ex: '+55 19 98903-3412')
            formatted_name = sender.get('formattedName', '')
            real_phone = _normalize_phone(formatted_name)
            
            # Prioridade 3: campos 'number' ou 'phone' no payload
            if not real_phone:
                real_phone = _normalize_phone(sender.get('number') or sender.get('phone'))
            
            # Prioridade 4: API do WPP Connect (resolve_phone_id - agora com múltiplas estratégias)
            if not real_phone and '@lid' in sender_id:
                print(f"[Webhook] LID detectado sem número no payload. Consultando WPP Connect API...")
                real_phone = wpp.resolve_phone_id(sender_id, session_name=session)
                if real_phone:
                    print(f"[Webhook] LID resolvido automaticamente: {real_phone}")
                else:
                    print(f"[Webhook] LID não pôde ser resolvido automaticamente")
            
            # Prioridade 5: Tentar resolver LID mesmo que não seja @lid (fallback)
            if not real_phone and not ('@c.us' in sender_id or '@s.whatsapp.net' in sender_id):
                print(f"[Webhook] ID desconhecido detectado. Tentando resolver...")
                real_phone = wpp.resolve_phone_id(sender_id, session_name=session)
                if real_phone:
                    print(f"[Webhook] ID desconhecido resolvido: {real_phone}")

        # Persiste no banco
        if real_phone:
            chat_session.update_user_data('real_phone', real_phone)
            print(f"[Webhook] real_phone salvo: {real_phone}")
            
            # Verifica se o número é válido no WhatsApp (diagnóstico)
            wpp.check_number_status(real_phone.split('@')[0], session_name=session)

        # 3. Processa IA
        chat_session.add_message('user', text)

        # Extrai dados da mensagem do usuário antes de chamar a IA
        from app.models.ai_model import _extract_data_from_user_message
        _extract_data_from_user_message(chat_session, text)

        ai_response = get_ai_response(chat_session)
        chat_session.add_message('assistant', ai_response)
        chat_session.save()

        # 4. Envia resposta
        # Determina o target_id: para @lid usa o real_phone se disponível
        if '@lid' in sender_id and real_phone:
            target_id = real_phone
            print(f"[Webhook] @lid detectado. Usando número real: {target_id}")
        else:
            target_id = sender_id

        print(f"[Webhook] Respondendo para: {target_id}")
        result = wpp.send_message(target_id, ai_response, session_name=session)

        # Garante que result é dict para chamar .get()
        if not isinstance(result, dict):
            result = {'status': 'error', 'message': str(result)}

        if result.get('status') != 'success':
            print(f"[Webhook] Envio direto falhou: {result.get('message', '?')}")
            # Para @lid sem real_phone: tenta send-reply usando o message_id original
            if '@lid' in sender_id and message_id:
                print(f"[Webhook] Tentando send-reply como fallback para @lid...")
                reply_result = wpp.send_reply(sender_id, ai_response, message_id, session_name=session)
                if isinstance(reply_result, dict) and reply_result.get('status') == 'success':
                    print(f"[Webhook] send-reply bem-sucedido!")
                else:
                    print(f"[Webhook] send-reply também falhou: {reply_result}")
        else:
            print(f"[Webhook] Resposta enviada com sucesso para {target_id}")

    except Exception as e:
        print(f"[Webhook] Erro ao processar mensagem de {sender_id}: {e}")
        import traceback
        traceback.print_exc()
