from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
import os

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Função para verificar se o usuário está autenticado
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login do painel administrativo"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Verificação simples de credenciais (em produção, use algo mais seguro)
        if username == 'admin' and password == 'senha123':
            session['admin_logged_in'] = True
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Credenciais inválidas', 'danger')
    
    return render_template('admin/login.html')

@admin_bp.route('/logout')
def logout():
    """Rota para logout"""
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))

@admin_bp.route('/')
@login_required
def dashboard():
    """Dashboard principal do painel administrativo"""
    return render_template('admin/dashboard.html')

@admin_bp.route('/conversas')
@login_required
def conversations():
    """Lista de conversas ativas e concluídas"""
    from app.models.chat_model import ChatSession
    conversations = ChatSession.get_all_sessions()
    return render_template('admin/conversations.html', conversations=conversations)

@admin_bp.route('/conversas/<conversation_id>')
@login_required
def view_conversation(conversation_id):
    """Visualiza uma conversa específica e recupera automaticamente o número real se necessário"""
    from app.models.chat_model import ChatSession
    from app.services.whatsapp_service import get_wpp_service
    
    conversation = ChatSession.get_session(conversation_id)
    if not conversation:
        flash('Conversa não encontrada', 'error')
        return redirect(url_for('admin.conversations'))
    
    # Recupera automaticamente o número real se for @lid e não tiver real_phone
    user_id = conversation['user_id']
    if '@lid' in user_id:
        chat_session = ChatSession(user_id)
        real_phone = chat_session.user_data.get('real_phone')
        
        if not real_phone:
            print(f"[View Conversation] @lid detectado sem real_phone. Tentando resolver...")
            try:
                wpp = get_wpp_service()
                session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
                resolved_phone = wpp.resolve_phone_id(user_id, session_name=session_name)
                if resolved_phone:
                    print(f"[View Conversation] Número resolvido: {resolved_phone}")
                    chat_session.update_user_data('real_phone', resolved_phone)
                    conversation['user_data']['real_phone'] = resolved_phone
            except Exception as e:
                print(f"[View Conversation] Erro ao resolver número: {e}")
    
    # Marca mensagens como lidas ao entrar na conversa
    try:
        chat_session = ChatSession(user_id)
        chat_session.mark_as_read()
    except Exception as e:
        print(f"[View Conversation] Erro ao marcar como lido: {e}")
    
    return render_template('admin/conversation_detail.html', conversation=conversation)

@admin_bp.route('/conversas/<conversation_id>/set-phone', methods=['POST'])
@login_required
def set_conversation_phone(conversation_id):
    """Salva o número de telefone real do cliente para uma conversa com ID @lid"""
    from app.models.chat_model import ChatSession
    
    data = request.get_json() or {}
    phone = data.get('phone', '').strip()
    
    if not phone:
        return jsonify({'status': 'error', 'message': 'Telefone é obrigatório'}), 400
        
    # Normaliza o telefone
    if not phone.endswith('@c.us') and not phone.endswith('@s.whatsapp.net'):
        # Remove caracteres não numéricos
        import re
        digits = re.sub(r'\D', '', phone)
        phone = f"{digits}@c.us"
    
    try:
        session_data = ChatSession.get_session(conversation_id)
        if not session_data:
            return jsonify({'status': 'error', 'message': 'Conversa não encontrada'}), 404
            
        chat_session = ChatSession(session_data['user_id'])
        chat_session.update_user_data('real_phone', phone)
        
        return jsonify({
            'status': 'success', 
            'message': f'Telefone {phone} associado com sucesso!',
            'phone': phone
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_bp.route('/conversas/<conversation_id>/send', methods=['POST'])
@login_required
def send_message(conversation_id):
    """Envia uma mensagem diretamente para o cliente via WhatsApp"""
    from app.models.chat_model import ChatSession
    from app.services.whatsapp_service import get_wpp_service

    data = request.get_json() or {}
    message_text = data.get('message', '').strip()

    if not message_text:
        return jsonify({'status': 'error', 'message': 'Mensagem vazia'}), 400

    try:
        session_data = ChatSession.get_session(conversation_id)
        if not session_data:
            return jsonify({'status': 'error', 'message': 'Conversa não encontrada'}), 404

        user_id = session_data['user_id']
        chat_session = ChatSession(user_id)

        # Pega o real_phone e last_message_id do banco
        real_phone = chat_session.user_data.get('real_phone')
        last_message_id = chat_session.user_data.get('last_message_id')

        wpp = get_wpp_service()
        session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')

        print(f"[Send Message] Iniciando envio para user_id={user_id}")
        print(f"[Send Message] real_phone no banco: {real_phone}")
        print(f"[Send Message] last_message_id: {last_message_id}")

        is_lid = '@lid' in user_id

        # --- Determina o target_id ---
        if is_lid:
            # Prioridade 1: Usa telefone já salvo no banco
            if real_phone:
                print(f"[Send Message] Usando telefone real salvo: {real_phone}")
                target_id = real_phone
            else:
                # Prioridade 2: Tenta resolver via API com múltiplas estratégias
                print(f"[Send Message] @lid sem real_phone. Tentando resolver via WPP API (estratégias avançadas)...")
                resolved_phone = wpp.resolve_phone_id(user_id, session_name=session_name)
                if resolved_phone:
                    real_phone = resolved_phone
                    chat_session.update_user_data('real_phone', real_phone)
                    print(f"[Send Message] Número resolvido automaticamente: {real_phone}. Salvando...")
                    target_id = real_phone
                else:
                    # Se não conseguir resolver, tenta usar send-reply como fallback
                    if last_message_id:
                        print(f"[Send Message] Tentando send-reply como fallback...")
                        result = wpp.send_reply(user_id, message_text, last_message_id, session_name=session_name)
                        if isinstance(result, dict) and result.get('status') == 'success':
                            chat_session.add_message('assistant', message_text)
                            chat_session.save()
                            return jsonify({'status': 'success', 'message': 'Mensagem enviada com sucesso via reply!'})
                        else:
                            return jsonify({
                                'status': 'error',
                                'message': (
                                    '⚠️ Este contato usa ID privado (@lid) e não foi possível resolver o número. '
                                    'O sistema tentou responder via reply mas também falhou. '
                                    'Aguardando o cliente enviar uma nova mensagem para tentar novamente.'
                                )
                            }), 422
                    else:
                        return jsonify({
                            'status': 'error',
                            'message': (
                                '⚠️ Este contato usa ID privado (@lid) e não foi possível resolver o número. '
                                'Aguardando o cliente enviar uma nova mensagem para criar um ponto de resposta.'
                            )
                        }), 422
        else:
            target_id = user_id

        print(f"[Send Message] Enviando para target_id: {target_id}")
        result = wpp.send_message(target_id, message_text, session_name=session_name)

        # Garante que result é sempre um dict
        if not isinstance(result, dict):
            result = {'status': 'error', 'message': str(result)}

        if result.get('status') == 'success':
            # Salva a mensagem no histórico do chat
            chat_session.add_message('assistant', message_text)
            chat_session.save()
            return jsonify({'status': 'success', 'message': 'Mensagem enviada com sucesso!'})
        else:
            error_msg = result.get('message', 'Erro desconhecido no envio')
            print(f"[Send Message] Falha: {error_msg}")
            return jsonify({'status': 'error', 'message': f'Falha no envio: {error_msg}'}), 500

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Send Message] Exceção: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/conversas/<conversation_id>/messages', methods=['GET'])
@login_required
def get_messages(conversation_id):
    """Retorna as mensagens de uma conversa como JSON (para polling AJAX)"""
    from app.models.chat_model import ChatSession
    session_data = ChatSession.get_session(conversation_id)
    if not session_data:
        return jsonify({'status': 'error', 'message': 'Conversa não encontrada'}), 404

    messages = []
    for msg in session_data.get('messages', []):
        ts = msg.get('timestamp')
        if hasattr(ts, 'strftime'):
            ts_str = ts.strftime('%d/%m/%Y %H:%M')
        else:
            ts_str = str(ts) if ts else ''
        messages.append({
            'role': msg.get('role', ''),
            'content': msg.get('content', ''),
            'timestamp': ts_str
        })

    return jsonify({
        'status': 'success',
        'messages': messages,
        'total': len(messages)
    })


@admin_bp.route('/conversas/updates', methods=['GET'])
@login_required
def get_conversation_updates():
    """Retorna o status de todas as conversas (para badges de notificação)"""
    from app.models.chat_model import ChatSession
    sessions = ChatSession.get_all_sessions()
    updates = []
    for s in sessions:
        updates.append({
            'id': s['id'],
            'unread_count': s.get('unread_count', 0),
            'last_message': s.get('last_message', ''),
            'updated_at': s['updated_at'].strftime('%H:%M') if hasattr(s['updated_at'], 'strftime') else str(s['updated_at'])
        })
    return jsonify({'status': 'success', 'updates': updates})


@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def settings():
    """Configurações do sistema"""
    from app.config.database import get_db_connection

    # Configurações padrão
    defaults = {
        'bot_name': 'AtendBot',
        'welcome_message': 'Olá! Sou o AtendBot, seu assistente virtual. Como posso te ajudar hoje?',
        'system_prompt': 'Você é um assistente virtual útil e profissional. Responda sempre em português.',
        'ai_model': 'gpt-3.5-turbo',
        'temperature': '0.7',
        'whatsapp_number': '',
        'session_name': 'marina_bot_session'
    }

    # Carrega configurações do banco
    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT setting_key, setting_value FROM ai_settings")
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            for row in rows:
                if row['setting_key'] in defaults:
                    defaults[row['setting_key']] = row['setting_value']
        except Exception as e:
            print(f"[Settings] Erro ao carregar configurações: {e}")

        # Carrega configurações do WhatsApp
        try:
            from app.models.whatsapp_model import WhatsAppConfig
            wa_config = WhatsAppConfig.get_config()
            if wa_config:
                defaults['whatsapp_number'] = wa_config.get('phone_number', '')
                defaults['session_name'] = wa_config.get('session_name', 'marina_bot_session')
        except Exception as e:
            print(f"[Settings] Erro ao carregar config WhatsApp: {e}")

        return render_template('admin/settings.html', **defaults)

    # Salva configurações
    if request.method == 'POST':
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Salva cada configuração
            settings_to_save = [
                'bot_name',
                'welcome_message',
                'system_prompt',
                'ai_model',
                'temperature'
            ]

            for key in settings_to_save:
                value = request.form.get(key, defaults[key])
                cursor.execute('''
                    INSERT INTO ai_settings (setting_key, setting_value)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE setting_value = %s, updated_at = NOW()
                ''', (key, value, value))

            # Salva configurações do WhatsApp (apenas session_name)
            session_name = request.form.get('session_name', defaults['session_name'])
            try:
                from app.models.whatsapp_model import WhatsAppConfig
                WhatsAppConfig.save_config(session_name=session_name)
            except Exception as e:
                print(f"[Settings] Erro ao salvar config WhatsApp: {e}")

            conn.commit()
            cursor.close()
            conn.close()

            flash('Configurações salvas com sucesso', 'success')
        except Exception as e:
            print(f"[Settings] Erro ao salvar configurações: {e}")
            flash('Erro ao salvar configurações', 'error')

        return redirect(url_for('admin.settings'))

@admin_bp.route('/clientes')
@login_required
def clients():
    """Página de gestão de clientes"""
    from app.models.chat_model import ChatSession
    conversations = ChatSession.get_all_sessions()
    clients_data = []
    for conv in conversations:
        client_info = {
            'id': conv['id'],
            'user_id': conv['user_id'],
            'nome': conv['user_data'].get('name') or conv['user_data'].get('nome') or 'Não informado',
            'email': conv['user_data'].get('email') or 'Não informado',
            'telefone': conv['user_data'].get('real_phone') or conv['user_data'].get('phone') or 'Não definido',
            'motivo_contato': conv['user_data'].get('motivo_contato') or 'Não informado',
            'data_inicio': conv['created_at'].strftime('%d/%m/%Y %H:%M'),
            'ultima_mensagem': conv['updated_at'].strftime('%d/%m/%Y %H:%M'),
            'status': conv['status'],
            'total_mensagens': len(conv.get('messages', [])),
            'dados_completos': bool(conv['user_data'].get('nome') and conv['user_data'].get('email') and conv['user_data'].get('motivo_contato'))
        }
        clients_data.append(client_info)
    clients_data.sort(key=lambda x: x['data_inicio'], reverse=True)
    return render_template('admin/clients.html', clients=clients_data)

@admin_bp.route('/clientes/<int:client_id>')
@login_required
def view_client(client_id):
    """Visualiza detalhes de um cliente específico"""
    from app.models.chat_model import ChatSession
    session_data = ChatSession.get_session(client_id)
    if not session_data:
        flash('Cliente não encontrado', 'error')
        return redirect(url_for('admin.clients'))
    
    return render_template('admin/client_detail.html', client=session_data)


@admin_bp.route('/conversas/<conversation_id>/resumo', methods=['POST'])
@login_required
def generate_conversation_summary(conversation_id):
    """Gera um resumo da conversa usando IA"""
    from app.models.chat_model import ChatSession
    from app.models.ai_model import get_ai_response
    
    try:
        # Obter a sessão completa
        chat_session = ChatSession.get_session(conversation_id)
        if not chat_session:
            return jsonify({'status': 'error', 'message': 'Conversa não encontrada'}), 404
        
        # Preparar mensagens para a IA
        messages_text = ""
        for msg in chat_session.get('messages', []):
            role = "Cliente" if msg.get('role') == 'user' else "Assistente"
            messages_text += f"{role}: {msg.get('content', '')}\n"
        
        # Criar prompt para resumo
        summary_prompt = f"""
        Você é um assistente especialista em analisar conversas sobre Salário Maternidade.
        
        Analise a seguinte conversa e gere um resumo estruturado:
        
        CONVERSA:
        {messages_text}
        
        DADOS COLETADOS:
        {chat_session.get('user_data', {})}
        
        Gere um resumo em formato JSON com os seguintes campos:
        - nome: Nome completo do cliente
        - telefone: Telefone do cliente
        - situacao_parto: Situação do parto (gravida/bebe_nasceu)
        - situacao_trabalho: Situação de trabalho atual
        - resumo_atendimento: Resumo do que já foi tratado na conversa
        - proximos_passos: Próximos passos recomendados
        - problemas: Problemas ou pendências identificadas
        
        Seja objetivo e profissional no resumo.
        """
        
        # Criar sessão temporária para o resumo
        temp_session = ChatSession(chat_session['user_id'])
        temp_session.add_message('system', summary_prompt)
        temp_session.add_message('user', messages_text)
        
        # Obter resumo da IA
        summary_response = get_ai_response(temp_session)
        
        # Tentar parsear como JSON
        import json
        try:
            # Procurar por JSON na resposta
            import re
            json_match = re.search(r'\{.*\}', summary_response, re.DOTALL)
            if json_match:
                summary_data = json.loads(json_match.group())
            else:
                # Se não encontrar JSON, criar estrutura manualmente
                summary_data = {
                    'nome': chat_session.get('user_data', {}).get('nome_completo', ''),
                    'telefone': chat_session.get('user_data', {}).get('telefone', ''),
                    'situacao_parto': chat_session.get('user_data', {}).get('situacao_parto', ''),
                    'situacao_trabalho': chat_session.get('user_data', {}).get('situacao_trabalho', ''),
                    'resumo_atendimento': summary_response,
                    'proximos_passos': 'Continuar coleta de documentos e análise do caso',
                    'problemas': 'Nenhum problema identificado'
                }
        except:
            summary_data = {
                'nome': chat_session.get('user_data', {}).get('nome_completo', ''),
                'telefone': chat_session.get('user_data', {}).get('telefone', ''),
                'situacao_parto': chat_session.get('user_data', {}).get('situacao_parto', ''),
                'situacao_trabalho': chat_session.get('user_data', {}).get('situacao_trabalho', ''),
                'resumo_atendimento': summary_response,
                'proximos_passos': 'Continuar coleta de documentos e análise do caso',
                'problemas': 'Nenhum problema identificado'
            }
        
        return jsonify({
            'status': 'success',
            'summary': summary_data
        })
        
    except Exception as e:
        print(f"[Summary] Erro ao gerar resumo: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': 'Erro ao gerar resumo da conversa'
        }), 500


@admin_bp.route('/conversas/<conversation_id>/exportar', methods=['POST'])
@login_required
def export_conversation_data(conversation_id):
    """Exporta dados completos da conversa em JSON"""
    from app.models.chat_model import ChatSession
    
    try:
        chat_session = ChatSession.get_session(conversation_id)
        if not chat_session:
            return jsonify({'status': 'error', 'message': 'Conversa não encontrada'}), 404
        
        # Preparar dados para exportação
        export_data = {
            'conversation_id': conversation_id,
            'user_id': chat_session.get('user_id'),
            'created_at': chat_session.get('created_at').isoformat() if chat_session.get('created_at') else None,
            'updated_at': chat_session.get('updated_at').isoformat() if chat_session.get('updated_at') else None,
            'status': chat_session.get('status'),
            'user_data': chat_session.get('user_data', {}),
            'messages': chat_session.get('messages', []),
            'unread_count': chat_session.get('unread_count', 0),
            'last_message': chat_session.get('last_message', '')
        }
        
        return jsonify(export_data)
        
    except Exception as e:
        print(f"[Export] Erro ao exportar conversa: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Erro ao exportar conversa'
        }), 500


@admin_bp.route('/leads')
@login_required
def leads():
    """Página de gerenciamento de leads"""
    from app.models.chat_model import ChatSession
    from datetime import datetime, timedelta
    
    # Obter parâmetros de filtro
    status_filter = request.args.get('status', '')
    date_filter = request.args.get('date_filter', '')
    search = request.args.get('search', '')
    
    # Obter todas as sessões
    all_sessions = ChatSession.get_all_sessions()
    
    # Filtrar leads
    filtered_leads = []
    for session in all_sessions:
        # Aplicar filtros
        if status_filter and session.get('status') != status_filter:
            continue
            
        if date_filter:
            if date_filter == 'today':
                if session.get('created_at').date() != datetime.now().date():
                    continue
            elif date_filter == 'week':
                if session.get('created_at') < datetime.now() - timedelta(days=7):
                    continue
            elif date_filter == 'month':
                if session.get('created_at') < datetime.now() - timedelta(days=30):
                    continue
        
        if search:
            search_lower = search.lower()
            user_data = session.get('user_data', {})
            nome = user_data.get('nome_completo', '').lower()
            user_id = session.get('user_id', '').lower()
            
            if search_lower not in nome and search_lower not in user_id:
                continue
        
        # Adicionar informações do lead
        lead_data = {
            'id': session.get('id'),
            'user_id': session.get('user_id'),
            'nome': session.get('user_data', {}).get('nome_completo'),
            'idade': session.get('user_data', {}).get('idade'),
            'real_phone': session.get('user_data', {}).get('real_phone'),
            'status': session.get('status', 'new'),
            'situacao_parto': session.get('user_data', {}).get('situacao_parto'),
            'situacao_trabalho': session.get('user_data', {}).get('situacao_trabalho'),
            'tentativa_anterior': session.get('user_data', {}).get('tentativa_anterior'),
            'created_at': session.get('created_at'),
            'updated_at': session.get('updated_at'),
            'user_data': session.get('user_data', {}),
            'unread_count': session.get('unread_count', 0),
            'last_message': session.get('last_message', '')
        }
        filtered_leads.append(lead_data)
    
    # Ordenar por data de criação (mais recentes primeiro)
    filtered_leads.sort(key=lambda x: x.get('created_at'), reverse=True)
    
    return render_template('admin/leads.html', leads=filtered_leads)


@admin_bp.route('/leads/<lead_id>/details', methods=['GET'])
@login_required
def get_lead_details(lead_id):
    """Obtém detalhes de um lead específico"""
    from app.models.chat_model import ChatSession
    
    try:
        session = ChatSession.get_session(lead_id)
        if not session:
            return jsonify({'status': 'error', 'message': 'Lead não encontrado'}), 404
        
        lead_data = {
            'id': session.get('id'),
            'user_id': session.get('user_id'),
            'nome': session.get('user_data', {}).get('nome_completo'),
            'idade': session.get('user_data', {}).get('idade'),
            'real_phone': session.get('user_data', {}).get('real_phone'),
            'status': session.get('status', 'new'),
            'situacao_parto': session.get('user_data', {}).get('situacao_parto'),
            'situacao_trabalho': session.get('user_data', {}).get('situacao_trabalho'),
            'tentativa_anterior': session.get('user_data', {}).get('tentativa_anterior'),
            'created_at': session.get('created_at'),
            'updated_at': session.get('updated_at'),
            'user_data': session.get('user_data', {}),
            'messages': session.get('messages', [])
        }
        
        return jsonify({'status': 'success', 'data': lead_data})
        
    except Exception as e:
        print(f"[Lead] Erro ao obter detalhes: {e}")
        return jsonify({'status': 'error', 'message': 'Erro ao obter detalhes do lead'}), 500


@admin_bp.route('/leads/update-status', methods=['POST'])
@login_required
def update_leads_status():
    """Atualiza status de múltiplos leads"""
    from app.models.chat_model import ChatSession
    
    try:
        data = request.get_json()
        lead_ids = data.get('ids', [])
        new_status = data.get('status')
        
        updated_count = 0
        for lead_id in lead_ids:
            session = ChatSession.get_session(lead_id)
            if session:
                session['status'] = new_status
                session.save()
                updated_count += 1
        
        return jsonify({
            'status': 'success',
            'message': f'{updated_count} leads atualizados com sucesso'
        })
        
    except Exception as e:
        print(f"[Lead] Erro ao atualizar status: {e}")
        return jsonify({'status': 'error', 'message': 'Erro ao atualizar status'}), 500


@admin_bp.route('/leads/transfer', methods=['POST'])
@login_required
def transfer_leads():
    """Transfere leads para atendimento humano"""
    from app.models.chat_model import ChatSession
    
    try:
        data = request.get_json()
        lead_ids = data.get('ids', [])
        notes = data.get('notes', '')
        transferred_to = data.get('transferred_to', 'human_team')
        
        transferred_count = 0
        for lead_id in lead_ids:
            session = ChatSession.get_session(lead_id)
            if session:
                # Atualizar status
                session['status'] = 'transferred'
                
                # Adicionar informações de transferência
                user_data = session.get('user_data', {})
                user_data.update({
                    'transferred_to': transferred_to,
                    'transferred_at': data.get('transferred_at', datetime.now().isoformat()),
                    'transfer_notes': notes
                })
                session['user_data'] = user_data
                
                session.save()
                transferred_count += 1
        
        return jsonify({
            'status': 'success',
            'message': f'{transferred_count} leads transferidos com sucesso'
        })
        
    except Exception as e:
        print(f"[Lead] Erro ao transferir: {e}")
        return jsonify({'status': 'error', 'message': 'Erro ao transferir leads'}), 500


@admin_bp.route('/leads/export', methods=['POST'])
@login_required
def export_leads():
    """Exporta leads selecionados para CSV"""
    from app.models.chat_model import ChatSession
    import csv
    from io import StringIO
    
    try:
        data = request.get_json()
        lead_ids = data.get('ids', [])
        
        # Obter leads
        leads_data = []
        for lead_id in lead_ids:
            session = ChatSession.get_session(lead_id)
            if session:
                user_data = session.get('user_data', {})
                lead_row = {
                    'ID': session.get('id'),
                    'Nome': user_data.get('nome_completo', ''),
                    'WhatsApp': session.get('user_id', ''),
                    'Telefone Real': user_data.get('real_phone', ''),
                    'Idade': user_data.get('idade', ''),
                    'Status': session.get('status', ''),
                    'Situação Parto': user_data.get('situacao_parto', ''),
                    'Situação Trabalho': user_data.get('situacao_trabalho', ''),
                    'Data Criação': session.get('created_at').strftime('%d/%m/%Y %H:%M') if session.get('created_at') else '',
                    'Última Atualização': session.get('updated_at').strftime('%d/%m/%Y %H:%M') if session.get('updated_at') else '',
                    'Mensagens Não Lidas': session.get('unread_count', 0),
                    'Última Mensagem': session.get('last_message', '')
                }
                leads_data.append(lead_row)
        
        # Criar CSV
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=leads_data[0].keys() if leads_data else [])
        writer.writeheader()
        writer.writerows(leads_data)
        
        # Retornar como arquivo
        from flask import Response
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=leads_export.csv'}
        )
        
    except Exception as e:
        print(f"[Lead] Erro ao exportar: {e}")
        return jsonify({'status': 'error', 'message': 'Erro ao exportar leads'}), 500
