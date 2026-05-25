from flask import Blueprint, request, jsonify
from app.models.chat_model import ChatSession
from app.models.ai_model import get_ai_response
from app.models.whatsapp_model import WhatsAppConfig
from app.services.audio_service import is_audio_message, transcribe_audio_message
import re
from collections import deque

webhook_bp = Blueprint('webhook', __name__)

# Proteção contra webhooks duplicados (guarda os últimos 200 IDs processados)
_processed_ids: set = set()
_processed_ids_queue: deque = deque(maxlen=200)


def _is_duplicate(message_id: str) -> bool:
    if not message_id or message_id in _processed_ids:
        return bool(message_id)
    _processed_ids.add(message_id)
    if len(_processed_ids_queue) == 200:
        _processed_ids.discard(_processed_ids_queue[0])
    _processed_ids_queue.append(message_id)
    return False


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
        message = data if data.get('content') or data.get('body') else data.get('message', {})
        if message.get('fromMe'):
            print(f"[Webhook] Mensagem própria (fromMe=True) ignorada.")
            return jsonify({'status': 'ok', 'note': 'fromMe ignored'})
        # Proteção contra webhook duplicado
        msg_id = message.get('id') or message.get('msgId') or ''
        if _is_duplicate(msg_id):
            print(f"[Webhook] Mensagem duplicada ignorada: {msg_id}")
            return jsonify({'status': 'ok', 'note': 'duplicate ignored'})
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
        message.get('caption') or
        message.get('text') or ''
    ).strip()

    # Para mensagens de áudio (PTT/voice), não usa body como texto
    audio_transcribed = False
    if not text and is_audio_message(message):
        print(f"[Webhook] Áudio recebido de {sender_id}. Iniciando transcrição...")

    print(f"[Webhook] Processando mensagem de {sender_id}: tipo={message.get('type','text')!r} texto='{text[:80]}'")

    # Ignora mensagens de grupo
    if message.get('isGroupMsg') or message.get('isGroup'):
        print(f"[Webhook] Mensagem de grupo ignorada.")
        return

    # Ignora mensagens sem remetente
    if not sender_id:
        print(f"[Webhook] Mensagem ignorada: sender_id ausente")
        return

    # Tenta transcrever áudio se não houver texto
    if not text and is_audio_message(message):
        try:
            from app.services.whatsapp_service import get_wpp_service
            wpp_temp = get_wpp_service()
            transcription = transcribe_audio_message(message, wpp_temp, session)
            if transcription:
                text = transcription
                audio_transcribed = True
                print(f"[Webhook] Áudio transcrito com sucesso: '{text[:80]}'")
            else:
                print(f"[Webhook] Transcrição falhou. Ignorando mensagem de áudio.")
                return
        except Exception as e:
            print(f"[Webhook] Erro ao transcrever áudio: {e}")
            return

    # Ignora mensagens sem texto (não-áudio e sem conteúdo)
    if not text:
        # Aceita o body como texto apenas se NÃO for mensagem de áudio
        text = (message.get('body') or '').strip()
        if not text:
            print(f"[Webhook] Mensagem ignorada: sem texto. sender_id={sender_id!r}")
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

        # 2. Salva nome do contato (pushname do WhatsApp) se ainda não tiver
        sender = message.get('sender', {})
        if not chat_session.user_data.get('nome_wpp'):
            pushname = (
                sender.get('pushname') or
                sender.get('shortName') or
                sender.get('name') or
                sender.get('formattedName', '')
            )
            # Salva somente se parecer um nome (não número de telefone)
            if pushname and not re.search(r'^\+?\d[\d\s\-\(\)]{6,}$', pushname):
                chat_session.update_user_data('nome_wpp', pushname)
                print(f"[Webhook] Nome WPP salvo: {pushname}")

        # 3. Tenta obter o número real para salvar como metadado
        # Prioridade 1: Já temos no banco?
        real_phone = chat_session.user_data.get('real_phone')
        
        if not real_phone:
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

        # 3. Adiciona mensagem do usuário e extrai dados
        # Se veio de áudio, armazena com prefixo para identificação no histórico
        stored_text = f"[🎤 Áudio transcrito]: {text}" if audio_transcribed else text
        chat_session.add_message('user', stored_text)

        from app.models.ai_model import _extract_data_from_user_message
        _extract_data_from_user_message(chat_session, text)

        # 4. Classificação automática no Kanban (não bloqueia)
        try:
            from app.services.kanban_service import auto_classify_session, get_session_kanban_stage, STAGES_BY_KEY
            _stage_antes = get_session_kanban_stage(chat_session.session_id)
            _qualificacao = chat_session.qualificacao
            auto_classify_session(chat_session.session_id, text, _qualificacao)
            _stage_depois = get_session_kanban_stage(chat_session.session_id)

            # Se mudou para um stage que requer agendamento → envia link de booking
            if _stage_depois != _stage_antes:
                _stage_obj = STAGES_BY_KEY.get(_stage_depois, {})
                if _stage_obj.get('requires_scheduling'):
                    try:
                        from app.controllers.booking_controller import get_booking_url
                        _booking_url = get_booking_url(
                            session_id=chat_session.session_id,
                            beneficio=_stage_obj.get('name', ''),
                        )
                        _link_msg = (
                            f"📅 Para este benefício, o atendimento é feito por consulta presencial.\n\n"
                            f"Acesse o link abaixo para escolher a data e o horário que melhor se encaixa para você:\n"
                            f"{_booking_url}\n\n"
                            f"É rápido e fácil! 😊"
                        )
                        wpp.send_message(sender_id, _link_msg, session_name=session)
                        print(f"[Webhook] Link de agendamento enviado para {sender_id}: {_booking_url}")
                    except Exception as _be:
                        print(f"[Webhook] Erro ao enviar link de agendamento: {_be}")
        except Exception as _ke:
            print(f"[Webhook] Kanban classify erro (ignorado): {_ke}")

        # 5. Gera resposta da IA (retorna None se IA estiver pausada)
        ai_response = get_ai_response(chat_session)

        if ai_response is None:
            # IA pausada: só salva a mensagem, sem enviar resposta automática
            chat_session.save()
            print(f"[Webhook] IA pausada para {sender_id}. Mensagem salva sem resposta automática.")
            return

        chat_session.add_message('assistant', ai_response)
        chat_session.save()

        # 5. Envia resposta ao cliente
        if '@lid' in sender_id and real_phone:
            target_id = real_phone
            print(f"[Webhook] @lid detectado. Usando número real: {target_id}")
        else:
            target_id = sender_id

        print(f"[Webhook] Respondendo para: {target_id}")
        result = wpp.send_message(target_id, ai_response, session_name=session)

        if not isinstance(result, dict):
            result = {'status': 'error', 'message': str(result)}

        if result.get('status') != 'success':
            print(f"[Webhook] Envio direto falhou: {result.get('message', '?')}")
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
