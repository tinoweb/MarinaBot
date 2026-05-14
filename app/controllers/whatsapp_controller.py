import os
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from app.controllers.admin_controller import login_required
from app.models.whatsapp_model import WhatsAppConfig
from app.services.whatsapp_service import get_wpp_service

whatsapp_bp = Blueprint('whatsapp', __name__, url_prefix='/admin/whatsapp')


@whatsapp_bp.route('/', methods=['GET'])
@login_required
def index():
    """Página de gerenciamento da conexão WhatsApp."""
    session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    config = WhatsAppConfig.get_config(session_name) or {}
    wpp = get_wpp_service()
    server_status = wpp.get_status(session_name)
    return render_template(
        'admin/whatsapp.html',
        config=config,
        session_name=session_name,
        server_status=server_status
    )


@whatsapp_bp.route('/connect', methods=['POST'])
@login_required
def connect():
    """Gera token e inicia sessão no WPP Connect Server."""
    session_name = (
        request.form.get('session_name') or
        os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    )
    wpp = get_wpp_service()
    wpp.session_name = session_name

    token = wpp.generate_token(session_name)
    if not token:
        flash('Não foi possível conectar ao servidor WPP Connect. Verifique se o container está rodando.', 'danger')
        return redirect(url_for('whatsapp.index'))

    wpp.start_session(session_name)
    flash('Sessão iniciada! Aguarde o QR Code aparecer e escaneie com seu celular.', 'success')
    return redirect(url_for('whatsapp.index'))


@whatsapp_bp.route('/qrcode', methods=['GET'])
@login_required
def qrcode():
    """Retorna o QR code atual como JSON (usado pelo polling do frontend)."""
    session_name = (
        request.args.get('session') or
        os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    )
    wpp = get_wpp_service()
    qr = wpp.get_qrcode(session_name)
    return jsonify({'qrcode': qr})


@whatsapp_bp.route('/status', methods=['GET'])
@login_required
def status():
    """Retorna status combinado (servidor + banco de dados) como JSON."""
    session_name = (
        request.args.get('session') or
        os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    )
    wpp = get_wpp_service()
    server_status = wpp.get_status(session_name)
    db_config = WhatsAppConfig.get_config(session_name) or {}

    server_wpp_status = server_status.get('status', '') if isinstance(server_status, dict) else ''
    db_status = db_config.get('status', 'unknown')

    if server_wpp_status == 'CONNECTED' and db_status != 'connected':
        phone = server_status.get('phone', '') or ''
        WhatsAppConfig.save_config(session_name=session_name, status='connected', phone_number=phone)
        db_status = 'connected'
        db_config['phone_number'] = phone

    return jsonify({
        'server': server_status,
        'db_status': db_status,
        'phone': db_config.get('phone_number', '')
    })


@whatsapp_bp.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    """Encerra a sessão WhatsApp (mantém autenticação)."""
    session_name = (
        request.form.get('session_name') or
        os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    )
    wpp = get_wpp_service()
    wpp.close_session(session_name)
    flash('Sessão encerrada com sucesso.', 'info')
    return redirect(url_for('whatsapp.index'))


@whatsapp_bp.route('/logout', methods=['POST'])
@login_required
def logout_device():
    """Desvincula o dispositivo (requer novo QR code)."""
    session_name = (
        request.form.get('session_name') or
        os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    )
    wpp = get_wpp_service()
    wpp.logout_session(session_name)
    flash('Dispositivo desvinculado. Será necessário escanear o QR Code novamente.', 'warning')
    return redirect(url_for('whatsapp.index'))


@whatsapp_bp.route('/restart-session', methods=['POST'])
@login_required
def restart_session():
    """Reinicia a sessão com o webhook configurado corretamente."""
    session_name = (
        request.form.get('session_name') or
        os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    )
    wpp = get_wpp_service()
    
    # Primeiro fecha a sessão se estiver aberta
    try:
        wpp.close_session(session_name)
    except:
        pass
    
    # Reinicia com o webhook configurado
    wpp.start_session(session_name)
    flash('Sessão reiniciada com webhook configurado! Escaneie o QR Code novamente se necessário.', 'success')
    return redirect(url_for('whatsapp.index'))


@whatsapp_bp.route('/refresh-webhook', methods=['POST'])
@login_required
def refresh_webhook():
    """Força a re-assinatura do webhook no WPP Connect."""
    session_name = (
        request.form.get('session_name') or
        os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
    )
    wpp = get_wpp_service()
    # Chama start_session novamente apenas para registrar o webhook (não reinicia a sessão se já logada)
    wpp.start_session(session_name)
    flash('Comando de atualização de Webhook enviado.', 'info')
    return redirect(url_for('whatsapp.index'))
