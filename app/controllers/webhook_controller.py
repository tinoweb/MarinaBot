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

    msg_type = (message.get('type') or '').lower()
    is_media_msg = message.get('isMedia') or msg_type in ('image', 'document', 'video')

    # Se for uma mensagem de mídia (imagem, documento, vídeo)
    is_other_media = False
    filename = message.get('filename') or ''
    if is_media_msg and not is_audio_message(message):
        is_other_media = True
        if not filename:
            mimetype = message.get('mimetype') or ''
            ext = mimetype.split('/')[-1].split(';')[0] if mimetype else 'bin'
            if ext == 'jpeg': ext = 'jpg'
            import uuid
            filename = f"documento_{uuid.uuid4().hex[:8]}.{ext}"
        
        # Se não tiver legenda/texto, define uma descrição amigável para a IA e histórico
        if not text:
            text = f"📎 [Arquivo Recebido]: {filename}"

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

        # Se for mensagem de mídia, faz download e salva como anexo
        if is_other_media:
            try:
                _download_and_save_webhook_media(chat_session, message, session)
            except Exception as me:
                print(f"[Webhook] Erro ao baixar/salvar anexo: {me}")

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

        # 4. Registra estado antes do processamento da IA
        from app.services.kanban_service import auto_classify_session, get_session_kanban_stage, STAGES_BY_KEY
        _stage_antes = get_session_kanban_stage(chat_session.session_id)
        _qualif_antes = chat_session.qualificacao

        # Primeiro, classifica o estágio com base no texto de entrada (para que o contexto da IA tenha o benefício correto)
        try:
            auto_classify_session(chat_session.session_id, text, _qualif_antes)
            _stage_atual = get_session_kanban_stage(chat_session.session_id)
        except Exception as _ke:
            print(f"[Webhook] Kanban pre-classify erro: {_ke}")
            _stage_atual = _stage_antes

        # 5. Gera resposta da IA (retorna None se IA estiver pausada)
        ai_response = get_ai_response(chat_session)

        if ai_response is None:
            # IA pausada: só salva a mensagem, sem enviar resposta automática
            chat_session.save()
            print(f"[Webhook] IA pausada para {sender_id}. Mensagem salva sem resposta automática.")
            return

        chat_session.add_message('assistant', ai_response)
        chat_session.save()

        # 6. Classificação pós-processamento da IA (se a qualificação mudou)
        try:
            _qualificacao_depois = chat_session.qualificacao
            auto_classify_session(chat_session.session_id, text, _qualificacao_depois)
            _stage_depois = get_session_kanban_stage(chat_session.session_id)

            # Envia link de booking se o estágio final exigir agendamento AND estiver qualificado
            _stage_obj = STAGES_BY_KEY.get(_stage_depois, {})
            if _stage_obj.get('requires_scheduling') and _qualificacao_depois == 'qualificada':
                # Envia apenas se o lead acabou de se qualificar nesta mensagem, ou se o estágio mudou
                if _qualif_antes != 'qualificada' or _stage_depois != _stage_antes:
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
            print(f"[Webhook] Kanban post-classify erro (ignorado): {_ke}")

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


def _download_and_save_webhook_media(chat_session, message, session_name):
    """Faz download e salva o arquivo de mídia enviado pelo WhatsApp."""
    import base64
    import os
    import requests
    import uuid
    from app.config.database import get_db_connection
    from app.services.whatsapp_service import get_wpp_service

    message_id = message.get('id') or message.get('msgId')
    mimetype = message.get('mimetype') or ''
    filename = message.get('filename') or message.get('caption') or ''
    msg_type = message.get('type') or ''

    # Define nome de arquivo caso esteja vazio
    if not filename:
        ext = ''
        if mimetype:
            ext = mimetype.split('/')[-1].split(';')[0]
            if ext == 'jpeg': ext = 'jpg'
        if not ext:
            ext = 'bin'
        filename = f"whatsapp_file_{uuid.uuid4().hex[:8]}.{ext}"

    media_data = None
    body = message.get('body') or ''

    # 1. Decodifica se for data URI
    if body.startswith('data:'):
        try:
            header, b64data = body.split(',', 1)
            media_data = base64.b64decode(b64data)
        except Exception as e:
            print(f"[Webhook Media] Erro ao decodificar data URI: {e}")

    # 2. Decodifica se for base64 puro
    if not media_data and body and not body.startswith('http') and len(body) > 100:
        try:
            media_data = base64.b64decode(body + '==')
        except Exception:
            pass

    # 3. Baixa se for uma URL
    if not media_data:
        media_url = message.get('mediaUrl') or (body if body.startswith('http') else None)
        if media_url:
            try:
                resp = requests.get(media_url, timeout=30)
                if resp.status_code == 200:
                    media_data = resp.content
            except Exception as e:
                print(f"[Webhook Media] Erro ao baixar da URL: {e}")

    # 4. Baixa via API do WPP Connect
    if not media_data and message_id:
        try:
            wpp = get_wpp_service()
            media_data, mime_from_api = wpp.download_media(message_id, session_name)
        except Exception as e:
            print(f"[Webhook Media] Erro no download da API: {e}")

    if not media_data:
        print(f"[Webhook Media] Não foi possível obter bytes da mídia {message_id}")
        return False

    try:
        # Cria diretório de uploads
        upload_dir = os.path.join('app', 'static', 'uploads', 'documents')
        os.makedirs(upload_dir, exist_ok=True)

        # Gera nome único
        base, ext = os.path.splitext(filename)
        if not ext and mimetype:
            ext = '.' + mimetype.split('/')[-1].split(';')[0]
            if ext == '.jpeg': ext = '.jpg'
        
        unique_name = f"{uuid.uuid4().hex}_{os.path.basename(filename)}"
        file_path = os.path.join(upload_dir, unique_name)
        
        with open(file_path, 'wb') as f:
            f.write(media_data)

        # Registra no banco
        relative_path = f"uploads/documents/{unique_name}"
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_attachments (session_id, message_id, file_name, file_path, mime_type, file_size) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (chat_session.session_id, message_id, filename, relative_path, mimetype, len(media_data))
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[Webhook Media] Arquivo salvo: {filename} -> {relative_path}")
        return True
    except Exception as e:
        print(f"[Webhook Media] Erro ao salvar arquivo: {e}")
        return False

