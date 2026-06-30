"""
Página pública de agendamento — acessível pelo cliente sem login.
URL: /agendar  (compartilhada pelo bot via WhatsApp)
"""

import os
from flask import Blueprint, request, render_template, jsonify
from datetime import date, timedelta
import calendar as _cal

from unicodedata import normalize
import re

booking_bp = Blueprint('booking', __name__, url_prefix='/agendar')

MESES_PT = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
            'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

DIAS_PT = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']
DIAS_FULL = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira',
             'Quinta-feira', 'Sexta-feira', 'Sábado']

SLUG_MAP = {
    'aposentadoria': 'Aposentadoria',
    'salario-maternidade': 'Salário Maternidade',
    'auxilio-doenca': 'Auxílio Doença',
    'pensao-por-morte': 'Pensão por Morte',
    'bpc-loas-idoso': 'BPC/LOAS Idoso',
    'bpc-loas-deficiente': 'BPC/LOAS Deficiente',
    'auxilio-acidente': 'Auxílio Acidente',
    'auxilio-reclusao': 'Auxílio Reclusão',
}

def decode_slug(slug: str) -> str:
    if not slug:
        return ''
    slug_lower = slug.lower()
    if slug_lower in SLUG_MAP:
        return SLUG_MAP[slug_lower]
    return slug.replace('-', ' ').title()


@booking_bp.route('', defaults={'session_id': None, 'beneficio_slug': None})
@booking_bp.route('/s/<int:session_id>', defaults={'beneficio_slug': None})
@booking_bp.route('/s/<int:session_id>/<beneficio_slug>')
def booking_page(session_id, beneficio_slug):
    """Página pública de agendamento estilo Calendly com URL amigável."""
    from app.services.agenda_service import get_bloqueios, get_config_semanal

    if session_id is None:
        try:
            session_id = int(request.args.get('sessao') or 0) or None
        except ValueError:
            session_id = None

    beneficio = ''
    if beneficio_slug:
        beneficio = decode_slug(beneficio_slug)
    else:
        beneficio = request.args.get('beneficio', '')

    token = request.args.get('token', '')

    hoje = date.today()
    mes  = int(request.args.get('mes', hoje.month))
    ano  = int(request.args.get('ano', hoje.year))

    # Garante que não navega para meses passados
    if ano < hoje.year or (ano == hoje.year and mes < hoje.month):
        mes, ano = hoje.month, hoje.year

    config = get_config_semanal()
    dias_ativos_db = {c['dia_semana'] for c in config if c.get('ativo')}
    bloqueios = get_bloqueios(mes, ano)

    # Gera calendário (semanas × 7 dias, col 0=Dom…6=Sab)
    cal_raw = _cal.monthcalendar(ano, mes)

    cal_weeks = []
    for semana in cal_raw:
        reordenado = [semana[6], semana[0], semana[1], semana[2],
                      semana[3], semana[4], semana[5]]
        linha = []
        for col_idx, dia in enumerate(reordenado):
            if dia == 0:
                linha.append({'dia': 0, 'estado': 'vazio', 'data': ''})
                continue
            data_str = f"{ano:04d}-{mes:02d}-{dia:02d}"
            dia_db = col_idx  # 0=Dom,1=Seg,...,6=Sab
            passado = data_str < str(hoje)
            bloqueado = data_str in bloqueios
            ativo = dia_db in dias_ativos_db

            if passado:
                estado = 'passado'
            elif bloqueado:
                estado = 'bloqueado'
            elif ativo:
                estado = 'disponivel'
            else:
                estado = 'indisponivel'

            linha.append({
                'dia': dia,
                'data': data_str,
                'estado': estado,
                'hoje': data_str == str(hoje),
            })
        cal_weeks.append(linha)

    # Navegação de mês
    if mes == 12:
        mes_prox, ano_prox = 1, ano + 1
    else:
        mes_prox, ano_prox = mes + 1, ano

    # Nome da advogada/escritório (pode vir de ai_settings)
    nome_escritorio = _get_setting('nome_escritorio', 'Dra. Marina Marques')
    subtitulo = _get_setting('booking_subtitulo',
                             'Agende sua consulta gratuita de avaliação de benefícios INSS')

    return render_template('booking.html',
        cal_weeks=cal_weeks,
        mes=mes, ano=ano,
        nome_mes=MESES_PT[mes],
        mes_prox=mes_prox, ano_prox=ano_prox,
        dias_pt=DIAS_PT,
        hoje=str(hoje),
        session_id=session_id or '',
        beneficio=beneficio,
        token=token,
        nome_escritorio=nome_escritorio,
        subtitulo=subtitulo,
    )


@booking_bp.route('/slots/<data_str>')
def slots(data_str):
    """Retorna horários disponíveis para uma data (JSON — sem login)."""
    from app.services.agenda_service import get_horarios_disponiveis
    try:
        d = date.fromisoformat(data_str)
    except ValueError:
        return jsonify({'error': 'Data inválida'}), 400

    horarios = get_horarios_disponiveis(data_str)
    dia_semana = DIAS_FULL[(d.weekday() + 1) % 7]
    dia_br = d.strftime('%d/%m/%Y')

    return jsonify({
        'data': data_str,
        'data_br': dia_br,
        'dia_semana': dia_semana,
        'horarios': horarios,
    })


@booking_bp.route('/confirmar', methods=['POST'])
def confirmar():
    """Cria o agendamento a partir do formulário público."""
    from app.services.agenda_service import criar_agendamento

    data_json = request.get_json(silent=True) or {}
    data_str     = data_json.get('data', '')
    hora         = data_json.get('hora', '')
    nome         = (data_json.get('nome') or '').strip()
    telefone     = (data_json.get('telefone') or '').strip()
    beneficio    = (data_json.get('beneficio') or '').strip()
    session_id   = int(data_json.get('session_id') or 0)

    if not all([data_str, hora, nome, telefone]):
        return jsonify({'success': False, 'message': 'Preencha todos os campos obrigatórios.'}), 400

    result = criar_agendamento(
        session_id=session_id,
        data_str=data_str,
        hora=hora,
        beneficio=beneficio,
        nome_cliente=nome,
        telefone=telefone,
    )
    return jsonify(result), 200 if result['success'] else 400


def _get_setting(key: str, default: str = '') -> str:
    """Lê configuração da tabela ai_settings."""
    try:
        from app.config.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT setting_value FROM ai_settings WHERE setting_key=%s LIMIT 1", (key,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return row['setting_value'] if row else default
    except Exception:
        return default


def get_booking_url(session_id: int = None, beneficio: str = '') -> str:
    """Gera a URL pública de agendamento amigável e profissional."""
    base = os.getenv('BASE_URL', 'https://advconnect.tech').rstrip('/')
    if session_id:
        if beneficio:
            # Converte benefício em slug limpo
            slug = normalize('NFKD', beneficio).encode('ascii', 'ignore').decode('ascii').lower()
            slug = re.sub(r'[^a-z0-9\-]', '', slug.replace(' ', '-'))
            slug = re.sub(r'-+', '-', slug).strip('-')
            return f"{base}/agendar/s/{session_id}/{slug}"
        return f"{base}/agendar/s/{session_id}"
    return f"{base}/agendar"
