from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
import os
from app.config.database import get_db_connection

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
        
        admin_user = os.getenv('ADMIN_USER', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin')
        if username == admin_user and password == admin_password:
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
    """Dashboard principal com dados reais do banco."""
    stats = {
        'total': 0, 'active': 0, 'closed': 0,
        'qualificadas': 0, 'aguardando_docs': 0, 'descarte': 0,
        'hoje': 0, 'semana': []
    }
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions")
        stats['total'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE status='active'")
        stats['active'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE status='closed'")
        stats['closed'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE qualificacao='qualificada'")
        stats['qualificadas'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE qualificacao='aguardando_docs'")
        stats['aguardando_docs'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE qualificacao IN ('descarte_1','descarte_2')")
        stats['descarte'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE DATE(created_at)=CURDATE()")
        stats['hoje'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("""
            SELECT DATE(created_at) AS dia, COUNT(*) AS total
            FROM chat_sessions
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
            GROUP BY dia ORDER BY dia ASC
        """)
        stats['semana'] = [{'dia': str(r['dia']), 'total': r['total']} for r in cursor.fetchall()]

        cursor.execute("""
            SELECT COUNT(*) AS n FROM chat_sessions
            WHERE status='active' AND ia_pausada=0
              AND ultimo_contato_at IS NOT NULL
              AND ultimo_contato_at < NOW() - INTERVAL 2 HOUR
        """)
        stats['inativos_2h'] = (cursor.fetchone() or {}).get('n', 0)

        cursor.execute("""
            SELECT cs.*, ud_nome.value AS nome_display
            FROM chat_sessions cs
            LEFT JOIN user_data ud_nome ON ud_nome.session_id=cs.id
                AND ud_nome.key_name IN ('nome_completo','nome','nome_wpp')
            ORDER BY cs.updated_at DESC LIMIT 10
        """)
        stats['recentes'] = cursor.fetchall()

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[Dashboard] Erro ao carregar stats: {e}")
        stats['recentes'] = []

    return render_template('admin/dashboard.html', stats=stats)


@admin_bp.route('/dashboard/stats')
@login_required
def dashboard_stats():
    """API JSON com estatísticas em tempo real para polling."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions")
        total = (cursor.fetchone() or {}).get('n', 0)
        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE status='active'")
        active = (cursor.fetchone() or {}).get('n', 0)
        cursor.execute("SELECT COUNT(*) AS n FROM chat_sessions WHERE unread_count > 0")
        unread = (cursor.fetchone() or {}).get('n', 0)
        cursor.close()
        conn.close()
        return jsonify({'status': 'success', 'total': total, 'active': active, 'unread': unread})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
    
    user_id = conversation['user_id']
    chat_session = ChatSession(user_id)
    wpp = get_wpp_service()
    session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')

    # Recupera número real para @lid
    if '@lid' in user_id and not chat_session.user_data.get('real_phone'):
        try:
            resolved_phone = wpp.resolve_phone_id(user_id, session_name=session_name)
            if resolved_phone:
                chat_session.update_user_data('real_phone', resolved_phone)
                conversation['user_data']['real_phone'] = resolved_phone
        except Exception as e:
            print(f"[View Conversation] Erro ao resolver número: {e}")

    # Enriquece nome via WPP Connect API se ainda não tiver
    if not chat_session.user_data.get('nome_wpp'):
        try:
            info = wpp.get_contact_info(user_id, session_name=session_name)
            if info.get('name'):
                chat_session.update_user_data('nome_wpp', info['name'])
                conversation['user_data']['nome_wpp'] = info['name']
        except Exception as e:
            print(f"[View Conversation] Erro ao buscar nome WPP: {e}")

    # Atualiza conversation com dados mais recentes do banco
    conversation['user_data'] = chat_session.user_data

    # Formata telefone para exibição
    raw_phone = (
        conversation['user_data'].get('real_phone') or
        (user_id if ('@c.us' in user_id or '@s.whatsapp.net' in user_id) else None)
    )
    if raw_phone:
        digits = raw_phone.split('@')[0]
        if len(digits) >= 12:
            conversation['phone_display'] = f"+{digits[:2]} ({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
        else:
            conversation['phone_display'] = digits
    elif '@lid' in user_id:
        conversation['phone_display'] = f"Privado (ID: {user_id.split('@')[0][:12]}...)"
    else:
        conversation['phone_display'] = user_id

    # Nome para exibição (prioridade: nome_completo > nome > nome_wpp > "Não informado")
    ud = conversation['user_data']
    conversation['name_display'] = (
        ud.get('nome_completo') or ud.get('nome') or ud.get('nome_wpp') or 'Não informado'
    )

    # Campos de gestão profissional
    conversation['ia_pausada'] = chat_session.ia_pausada
    conversation['qualificacao'] = chat_session.qualificacao or 'pendente'
    conversation['etapa_atual'] = chat_session.etapa_atual or 1

    # Marca mensagens como lidas
    try:
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
    # Configurações padrão
    defaults = {
        'bot_name': 'Assistente da Dra. Marina',
        'welcome_message': 'Olá! Aqui é a assistente da Dra. Marina Marques, advogada especialista em benefícios do INSS.\n\nMe conta: com qual benefício posso te ajudar hoje?',
        'system_prompt': '',
        'ai_model': 'gpt-4o-mini',
        'temperature': '0.4',
        'instagram_handle': '@drainss',
        'followup_enabled': 'true',
        'whatsapp_number': '',
        'session_name': 'marina_bot_session',
        'admin_phone': ''
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
                'temperature',
                'instagram_handle',
                'followup_enabled',
                'admin_phone',
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

        ud = session.get('user_data', {})

        lead_data = {
            'id': session.get('id'),
            'user_id': session.get('user_id'),
            'real_phone': ud.get('real_phone'),
            'nome': ud.get('nome_completo') or ud.get('nome') or ud.get('nome_wpp'),
            'idade': ud.get('idade'),
            'status': session.get('status', 'active'),
            'ia_pausada': session.get('ia_pausada', 0),
            'qualificacao': session.get('qualificacao') or 'pendente',
            'etapa_atual': session.get('etapa_atual', 1),
            'situacao_parto': ud.get('situacao_parto'),
            'situacao_trabalho': ud.get('situacao_trabalho'),
            'tentativa_anterior': ud.get('tentativa_anterior'),
            'created_at': str(session.get('created_at', '')),
            'updated_at': str(session.get('updated_at', '')),
            'user_data': ud,
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


# ──────────────────────────────────────────────────────────────────────────────
# CONTROLE DA IA POR CONVERSA
# ──────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/conversas/<conversation_id>/toggle-ia', methods=['POST'])
@login_required
def toggle_ia(conversation_id):
    """Liga/desliga a IA para uma conversa específica."""
    from app.models.chat_model import ChatSession
    try:
        session_data = ChatSession.get_session(conversation_id)
        if not session_data:
            return jsonify({'status': 'error', 'message': 'Conversa não encontrada'}), 404

        novo_estado = 0 if session_data.get('ia_pausada', 0) else 1

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET ia_pausada = %s WHERE id = %s",
            (novo_estado, conversation_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        label = 'pausada' if novo_estado else 'ativa'
        return jsonify({
            'status': 'success',
            'ia_pausada': novo_estado,
            'message': f'IA {label} para esta conversa.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/conversas/<conversation_id>/qualificacao', methods=['POST'])
@login_required
def update_qualificacao(conversation_id):
    """Atualiza o status de qualificação de uma conversa."""
    data = request.get_json() or {}
    qualificacao = data.get('qualificacao', '').strip()

    VALORES_VALIDOS = {
        'pendente', 'qualificada', 'descarte_1', 'descarte_2',
        'aguardando_docs', 'docs_recebidos', 'fechamento', 'pos_venda'
    }
    if qualificacao not in VALORES_VALIDOS:
        return jsonify({'status': 'error', 'message': 'Valor inválido'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET qualificacao = %s WHERE id = %s",
            (qualificacao, conversation_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'status': 'success', 'qualificacao': qualificacao})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/templates', methods=['GET'])
@login_required
def get_templates():
    """Retorna os templates de mensagens rápidas."""
    from app.models.ai_model import _get_ai_setting
    instagram = _get_ai_setting('instagram_handle', '@drainss')

    templates = [
        {
            'id': 'honorarios',
            'label': '💰 Honorários',
            'text': (
                "Nossa assessoria trabalha com honorários de 30% sobre o valor do benefício, "
                "cobrados apenas em caso de êxito — sem custos antecipados para você.\n\n"
                "Ou seja: você só paga se ganhar. ✅"
            )
        },
        {
            'id': 'documentos',
            'label': '📎 Documentos Necessários',
            'text': (
                "Para darmos início ao processo, precisamos dos seguintes documentos:\n\n"
                "📄 *Documentos básicos:*\n"
                "• RG e CPF\n"
                "• Comprovante de residência\n"
                "• Carteira de trabalho (ou extrato do CNIS pelo Gov.br)\n"
                "• Certidão de nascimento do bebê ou declaração hospitalar\n\n"
                "Você consegue reunir esses documentos? 😊"
            )
        },
        {
            'id': 'encaminhar_dra',
            'label': '👩‍⚖️ Encaminhar para Dra. Marina',
            'text': (
                "Ótimo! Vou encaminhar o seu caso diretamente para a Dra. Marina. "
                "Ela vai analisar e retornar o mais breve possível. 👩‍⚖️\n\n"
                f"Enquanto isso, você pode acompanhar nosso trabalho no Instagram: {instagram}"
            )
        },
        {
            'id': 'followup_1h',
            'label': '🔔 Follow-up (Recuperação)',
            'text': (
                "Oi! Tudo bem por aí?\n\n"
                "Vi que nossa conversa ficou por aqui. Queria saber se ficou "
                "alguma dúvida que posso ajudar. 😊\n\n"
                "Estou à disposição!"
            )
        },
        {
            'id': 'followup_24h',
            'label': '⚠️ Follow-up (Urgência)',
            'text': (
                "Olá! Passando para lembrar que o Salário Maternidade tem prazo.\n\n"
                "Quanto mais perto do parto, menos tempo para garantir o benefício "
                "com segurança.\n\n"
                "A Dra. Marina ainda consegue analisar o seu caso — mas o ideal é "
                "agir agora. ✅\n\n"
                "Quer que eu encaminhe para ela?"
            )
        },
        {
            'id': 'prazo_urgente',
            'label': '🚨 Prazo Urgente (pós-parto)',
            'text': (
                "O prazo para garantir o benefício vai até o dia 15 do mês seguinte "
                "ao nascimento.\n\n"
                "A Dra. Marina ainda consegue analisar — mas precisa ser agora.\n\n"
                "Quer que eu encaminhe? ✅"
            )
        },
    ]
    return jsonify({'status': 'success', 'templates': templates})


# ─── NOTAS INTERNAS ───────────────────────────────────────────────────────────

@admin_bp.route('/conversas/<int:conversation_id>/notes', methods=['GET'])
@login_required
def get_notes(conversation_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, note, created_at FROM conversation_notes WHERE session_id = %s ORDER BY created_at DESC",
            (conversation_id,)
        )
        notes = cur.fetchall()
        cur.close(); conn.close()
        for n in notes:
            if n.get('created_at'):
                n['created_at'] = n['created_at'].strftime('%d/%m/%Y %H:%M')
        return jsonify({'status': 'success', 'notes': notes})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/conversas/<int:conversation_id>/notes', methods=['POST'])
@login_required
def add_note(conversation_id):
    data = request.get_json() or {}
    note_text = (data.get('note') or '').strip()
    if not note_text:
        return jsonify({'status': 'error', 'message': 'Nota vazia'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO conversation_notes (session_id, note) VALUES (%s, %s)",
            (conversation_id, note_text)
        )
        note_id = cur.lastrowid
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status': 'success', 'id': note_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/conversas/<int:conversation_id>/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_note(conversation_id, note_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM conversation_notes WHERE id = %s AND session_id = %s",
            (note_id, conversation_id)
        )
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── CHECKLIST DE DOCUMENTOS ─────────────────────────────────────────────────

DOCS_PADRAO = [
    ('rg_cpf',              'RG / CPF'),
    ('comprovante_end',     'Comprovante de Residência'),
    ('ctps_cnis',           'Carteira de Trabalho / CNIS'),
    ('certidao_nascimento', 'Certidão de Nasc. do Bebê'),
    ('declaracao_parto',    'Declaração de Nascido Vivo'),
    ('comprovante_inss',    'Comprovante de Contribuição INSS'),
]


@admin_bp.route('/conversas/<int:conversation_id>/checklist', methods=['GET'])
@login_required
def get_checklist(conversation_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT doc_type, checked FROM document_checklist WHERE session_id = %s",
            (conversation_id,)
        )
        rows = {r['doc_type']: r['checked'] for r in cur.fetchall()}
        cur.close(); conn.close()
        result = [
            {'key': k, 'label': lbl, 'checked': bool(rows.get(k, 0))}
            for k, lbl in DOCS_PADRAO
        ]
        return jsonify({'status': 'success', 'checklist': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/conversas/<int:conversation_id>/checklist', methods=['POST'])
@login_required
def update_checklist(conversation_id):
    data = request.get_json() or {}
    doc_type = data.get('doc_type')
    checked = 1 if data.get('checked') else 0
    if not doc_type:
        return jsonify({'status': 'error', 'message': 'doc_type obrigatório'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO document_checklist (session_id, doc_type, checked) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE checked = %s",
            (conversation_id, doc_type, checked, checked)
        )
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── FOLLOW-UP AGENDADO MANUAL ────────────────────────────────────────────────

@admin_bp.route('/conversas/<int:conversation_id>/schedule-followup', methods=['GET'])
@login_required
def get_scheduled_followups(conversation_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, scheduled_at, message, sent FROM scheduled_followups "
            "WHERE session_id = %s ORDER BY scheduled_at ASC",
            (conversation_id,)
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        for r in rows:
            if r.get('scheduled_at'):
                r['scheduled_at'] = r['scheduled_at'].strftime('%d/%m/%Y %H:%M')
        return jsonify({'status': 'success', 'followups': rows})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/conversas/<int:conversation_id>/schedule-followup', methods=['POST'])
@login_required
def schedule_followup(conversation_id):
    data = request.get_json() or {}
    scheduled_at = data.get('scheduled_at')
    message = (data.get('message') or '').strip()
    if not scheduled_at or not message:
        return jsonify({'status': 'error', 'message': 'Data e mensagem obrigatórios'}), 400
    try:
        from datetime import datetime as _dt
        dt = _dt.strptime(scheduled_at, '%Y-%m-%dT%H:%M')
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scheduled_followups (session_id, scheduled_at, message) VALUES (%s, %s, %s)",
            (conversation_id, dt, message)
        )
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/conversas/<int:conversation_id>/schedule-followup/<int:sf_id>', methods=['DELETE'])
@login_required
def cancel_scheduled_followup(conversation_id, sf_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM scheduled_followups WHERE id = %s AND session_id = %s AND sent = 0",
            (sf_id, conversation_id)
        )
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── USO E CUSTO OPENAI ───────────────────────────────────────────────────────

# ─── AÇÕES RÁPIDAS ────────────────────────────────────────────────────────────

@admin_bp.route('/clear-all-conversations', methods=['POST'])
@login_required
def clear_all_conversations():
    """Apaga TODAS as conversas, mensagens e dados relacionados do banco."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM scheduled_followups")
        cur.execute("DELETE FROM document_checklist")
        cur.execute("DELETE FROM conversation_notes")
        cur.execute("DELETE FROM chat_messages")
        cur.execute("DELETE FROM user_data")
        cur.execute("DELETE FROM chat_sessions")
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'status': 'success', 'message': 'Todas as conversas foram removidas.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/clear-cache', methods=['POST'])
@login_required
def clear_cache():
    """Limpa dados em memória (sem estado persistente no momento)."""
    try:
        from app.models.chat_model import ChatSession
        ChatSession._sessions_cache = {}
    except Exception:
        pass
    return jsonify({'status': 'success', 'message': 'Cache limpo com sucesso.'})


@admin_bp.route('/restart-service', methods=['POST'])
@login_required
def restart_service():
    """Reinicia o scheduler de follow-ups sem derrubar o Flask."""
    try:
        from app.services.scheduler_service import restart_scheduler
        restart_scheduler()
        return jsonify({'status': 'success', 'message': 'Serviço reiniciado com sucesso.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── USO E CUSTO OPENAI ───────────────────────────────────────────────────────

@admin_bp.route('/openai/usage', methods=['GET'])
@login_required
def openai_usage():
    """Retorna estatísticas de uso e custo estimado dos tokens da OpenAI."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # Resumo total
        cur.execute("""
            SELECT
                COUNT(*) as total_requests,
                SUM(prompt_tokens) as total_prompt,
                SUM(completion_tokens) as total_completion,
                SUM(total_tokens) as total_tokens,
                SUM(estimated_cost_usd) as total_cost,
                MIN(created_at) as first_request,
                MAX(created_at) as last_request
            FROM token_usage
        """)
        total = cur.fetchone()

        # Uso do mês atual
        cur.execute("""
            SELECT
                SUM(total_tokens) as tokens_mes,
                SUM(estimated_cost_usd) as custo_mes
            FROM token_usage
            WHERE YEAR(created_at) = YEAR(NOW()) AND MONTH(created_at) = MONTH(NOW())
        """)
        mes = cur.fetchone()

        # Uso dos últimos 7 dias (por dia)
        cur.execute("""
            SELECT
                DATE(created_at) as dia,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as custo
            FROM token_usage
            WHERE created_at >= NOW() - INTERVAL 7 DAY
            GROUP BY DATE(created_at)
            ORDER BY dia ASC
        """)
        por_dia = cur.fetchall()
        for r in por_dia:
            if r.get('dia'):
                r['dia'] = str(r['dia'])

        # Por modelo
        cur.execute("""
            SELECT model,
                   SUM(total_tokens) as tokens,
                   SUM(estimated_cost_usd) as custo
            FROM token_usage
            GROUP BY model
            ORDER BY custo DESC
        """)
        por_modelo = cur.fetchall()

        cur.close(); conn.close()

        def _safe(val, decimals=2):
            if val is None:
                return 0
            try:
                return round(float(val), decimals)
            except Exception:
                return 0

        return jsonify({
            'status': 'success',
            'total': {
                'requests': total.get('total_requests', 0) or 0,
                'prompt_tokens': total.get('total_prompt', 0) or 0,
                'completion_tokens': total.get('total_completion', 0) or 0,
                'total_tokens': total.get('total_tokens', 0) or 0,
                'cost_usd': _safe(total.get('total_cost'), 4),
                'first_request': str(total.get('first_request', '')) if total.get('first_request') else None,
                'last_request': str(total.get('last_request', '')) if total.get('last_request') else None,
            },
            'mes_atual': {
                'tokens': mes.get('tokens_mes', 0) or 0,
                'cost_usd': _safe(mes.get('custo_mes'), 4),
            },
            'por_dia': por_dia,
            'por_modelo': por_modelo,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── KANBAN CRM ────────────────────────────────────────────────────────────────

@admin_bp.route('/kanban')
@login_required
def kanban():
    """Página principal do Kanban CRM."""
    from app.services.kanban_service import STAGES, get_board_data
    board = get_board_data()
    return render_template('admin/kanban.html', stages=STAGES, board=board)


@admin_bp.route('/kanban/data')
@login_required
def kanban_data():
    """API JSON com dados do board para polling em tempo real."""
    from app.services.kanban_service import STAGES, get_board_data
    board = get_board_data()
    serialized = {}
    for stage_key, cards in board.items():
        serialized[stage_key] = []
        for card in cards:
            c = dict(card)
            for k, v in c.items():
                if hasattr(v, 'isoformat'):
                    c[k] = v.isoformat()
            serialized[stage_key].append(c)
    return jsonify({'status': 'success', 'board': serialized, 'stages': STAGES})


@admin_bp.route('/kanban/move', methods=['POST'])
@login_required
def kanban_move():
    """Move um lead para uma stage específica (ação manual do admin)."""
    from app.services.kanban_service import move_session_to_stage, STAGES_BY_KEY
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    stage_key = data.get('stage_key')
    if not session_id or not stage_key:
        return jsonify({'status': 'error', 'message': 'session_id e stage_key são obrigatórios'}), 400
    if stage_key not in STAGES_BY_KEY:
        return jsonify({'status': 'error', 'message': f'Stage inválida: {stage_key}'}), 400
    ok = move_session_to_stage(int(session_id), stage_key)
    if ok:
        return jsonify({'status': 'success', 'message': f'Lead movido para {stage_key}'})
    return jsonify({'status': 'error', 'message': 'Falha ao mover lead'}), 500


# ── AGENDA / CALENDÁRIO ───────────────────────────────────────────────────────

@admin_bp.route('/agenda')
@login_required
def agenda():
    """Página principal da agenda com calendário e configuração."""
    from app.services.agenda_service import (
        get_config_semanal, get_agendamentos_por_data, get_bloqueios, DIAS_LABEL
    )
    from datetime import date as _date
    import calendar as _cal

    mes = int(request.args.get('mes', _date.today().month))
    ano = int(request.args.get('ano', _date.today().year))

    config_semanal = get_config_semanal()
    agendamentos_mes = get_agendamentos_por_data(mes, ano)
    bloqueios = get_bloqueios(mes, ano)

    # Gera estrutura do calendário (semanas × dias)
    cal = _cal.monthcalendar(ano, mes)
    nome_mes = [
        '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
    ][mes]

    # Identifica dias disponíveis (dia_semana ativo na config)
    dias_ativos = {c['dia_semana'] for c in config_semanal if c.get('ativo')}
    hoje = str(_date.today())

    return render_template('admin/agenda.html',
        config_semanal=config_semanal,
        calendario=cal,
        mes=mes, ano=ano,
        nome_mes=nome_mes,
        agendamentos_mes=agendamentos_mes,
        bloqueios=bloqueios,
        dias_ativos=dias_ativos,
        hoje=hoje,
        dias_label=DIAS_LABEL,
    )


@admin_bp.route('/agenda/config', methods=['POST'])
@login_required
def agenda_salvar_config():
    """Salva a configuração semanal de disponibilidade."""
    from app.services.agenda_service import salvar_config_dia
    data = request.get_json(silent=True) or {}
    dias = data.get('dias', [])
    erros = []
    for item in dias:
        ok = salvar_config_dia(
            dia_semana=int(item['dia_semana']),
            ativo=bool(item.get('ativo', False)),
            horarios=item.get('horarios', []),
            max_por_dia=int(item.get('max_por_dia', 5))
        )
        if not ok:
            erros.append(item['dia_semana'])
    if erros:
        return jsonify({'status': 'error', 'message': f'Erro nos dias: {erros}'}), 500
    return jsonify({'status': 'success', 'message': 'Configuração salva!'})


@admin_bp.route('/agenda/bloquear', methods=['POST'])
@login_required
def agenda_bloquear():
    """Bloqueia uma data específica."""
    from app.services.agenda_service import bloquear_data
    data = request.get_json(silent=True) or {}
    data_str = data.get('data', '')
    motivo = data.get('motivo', '')
    if not data_str:
        return jsonify({'status': 'error', 'message': 'Data obrigatória'}), 400
    ok = bloquear_data(data_str, motivo)
    return jsonify({'status': 'success' if ok else 'error'})


@admin_bp.route('/agenda/bloquear/<data_str>', methods=['DELETE'])
@login_required
def agenda_desbloquear(data_str):
    """Remove bloqueio de uma data."""
    from app.services.agenda_service import desbloquear_data
    ok = desbloquear_data(data_str)
    return jsonify({'status': 'success' if ok else 'error'})


@admin_bp.route('/agenda/disponibilidade/<data_str>')
@login_required
def agenda_disponibilidade(data_str):
    """Retorna horários disponíveis para uma data (usado pelo front e pelo bot)."""
    from app.services.agenda_service import get_horarios_disponiveis
    slots = get_horarios_disponiveis(data_str)
    return jsonify({'status': 'success', 'data': data_str, 'horarios': slots})


@admin_bp.route('/agenda/proximas')
@login_required
def agenda_proximas():
    """Retorna próximas datas disponíveis (usado pelo bot)."""
    from app.services.agenda_service import get_proximas_datas_disponiveis
    qtd = int(request.args.get('qtd', 3))
    datas = get_proximas_datas_disponiveis(quantidade=qtd)
    return jsonify({'status': 'success', 'datas': datas})


@admin_bp.route('/agenda/agendar', methods=['POST'])
@login_required
def agenda_criar():
    """Cria um agendamento (admin manual ou via bot)."""
    from app.services.agenda_service import criar_agendamento
    data = request.get_json(silent=True) or {}
    result = criar_agendamento(
        session_id=int(data.get('session_id', 0)),
        data_str=data.get('data', ''),
        hora=data.get('hora', ''),
        beneficio=data.get('beneficio', ''),
        nome_cliente=data.get('nome_cliente', ''),
        telefone=data.get('telefone', ''),
    )
    code = 200 if result['success'] else 400
    return jsonify(result), code


@admin_bp.route('/agenda/todos')
@login_required
def agenda_todos():
    """Retorna todos os agendamentos (opcionalmente filtrado por mes/ano)."""
    from app.services.agenda_service import get_agendamentos
    from datetime import date as _date
    mes  = request.args.get('mes',  type=int)
    ano  = request.args.get('ano',  type=int)
    agts = get_agendamentos(mes=mes, ano=ano)
    result = []
    for a in agts:
        result.append({
            'id':           a.get('id'),
            'data_br':      a.get('data_br', ''),
            'data':         str(a.get('data', '')),
            'hora':         str(a.get('hora', ''))[:5],
            'dia_semana':   a.get('dia_semana', ''),
            'nome_display': a.get('nome_display', ''),
            'telefone':     a.get('telefone', ''),
            'beneficio':    a.get('beneficio', ''),
            'status':       a.get('status', 'pendente'),
            'status_label': a.get('status_label', ''),
            'observacoes':  a.get('observacoes', '') or '',
        })
    return jsonify({'status': 'success', 'agendamentos': result, 'total': len(result)})


@admin_bp.route('/agenda/agendamentos-dia/<data_str>')
@login_required
def agenda_agendamentos_dia(data_str):
    """Retorna JSON com agendamentos de uma data específica."""
    from app.services.agenda_service import get_agendamentos
    agts = get_agendamentos(data_str=data_str)
    result = []
    for a in agts:
        result.append({
            'id':           a.get('id'),
            'hora':         str(a.get('hora', ''))[:5],
            'nome_display': a.get('nome_display', ''),
            'telefone':     a.get('telefone', ''),
            'beneficio':    a.get('beneficio', ''),
            'status':       a.get('status', 'pendente'),
            'status_label': a.get('status_label', ''),
            'observacoes':  a.get('observacoes', ''),
            'data_br':      a.get('data_br', ''),
        })
    return jsonify({'status': 'success', 'agendamentos': result})


@admin_bp.route('/agenda/agendamentos/<int:agt_id>', methods=['PATCH'])
@login_required
def agenda_atualizar(agt_id):
    """Atualiza status de um agendamento."""
    from app.services.agenda_service import atualizar_status
    data = request.get_json(silent=True) or {}
    ok = atualizar_status(agt_id, data.get('status', ''), data.get('observacoes'))
    return jsonify({'status': 'success' if ok else 'error'})
