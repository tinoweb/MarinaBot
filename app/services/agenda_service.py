"""
Serviço de Agenda/Calendário para agendamentos de consultas.
- Dra. Marina configura disponibilidade semanal (dias + horários)
- Pode bloquear datas específicas (feriados, folgas)
- Bot consulta disponibilidade e cria agendamentos automaticamente
"""

import json
from datetime import date, timedelta, datetime
from app.config.database import get_db_connection

DIAS_LABEL = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado']
DIAS_ABREV = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']

STATUS_LABEL = {
    'pendente':   'Pendente',
    'confirmado': 'Confirmado',
    'cancelado':  'Cancelado',
    'realizado':  'Realizado',
}


# ── Configuração semanal ──────────────────────────────────────────────────────

def get_config_semanal() -> list:
    """Retorna configuração de disponibilidade para os 7 dias da semana."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM agenda_config ORDER BY dia_semana")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        for row in rows:
            if isinstance(row.get('horarios'), str):
                row['horarios'] = json.loads(row['horarios'] or '[]')
            elif row.get('horarios') is None:
                row['horarios'] = []
            row['dia_label'] = DIAS_LABEL[row['dia_semana']]
        return rows
    except Exception as e:
        print(f"[Agenda] Erro ao carregar config semanal: {e}")
        return []


def salvar_config_dia(dia_semana: int, ativo: bool, horarios: list, max_por_dia: int = 5):
    """Salva ou atualiza configuração de disponibilidade de um dia da semana."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agenda_config (dia_semana, ativo, horarios, max_por_dia)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE ativo=%s, horarios=%s, max_por_dia=%s
        """, (
            dia_semana, int(ativo), json.dumps(horarios), max_por_dia,
            int(ativo), json.dumps(horarios), max_por_dia
        ))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[Agenda] Erro ao salvar config dia {dia_semana}: {e}")
        return False


# ── Bloqueios de datas ────────────────────────────────────────────────────────

def bloquear_data(data_str: str, motivo: str = '') -> bool:
    """Bloqueia uma data específica (impede agendamentos)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT IGNORE INTO agenda_bloqueios (data, motivo) VALUES (%s, %s)",
            (data_str, motivo)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[Agenda] Erro ao bloquear data: {e}")
        return False


def desbloquear_data(data_str: str) -> bool:
    """Remove bloqueio de uma data."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM agenda_bloqueios WHERE data=%s", (data_str,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[Agenda] Erro ao desbloquear data: {e}")
        return False


def get_bloqueios(mes: int = None, ano: int = None) -> set:
    """Retorna conjunto de datas bloqueadas (strings 'YYYY-MM-DD')."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if mes and ano:
            cursor.execute(
                "SELECT data FROM agenda_bloqueios WHERE MONTH(data)=%s AND YEAR(data)=%s",
                (mes, ano)
            )
        else:
            cursor.execute("SELECT data FROM agenda_bloqueios")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return {str(r['data']) for r in rows}
    except Exception as e:
        print(f"[Agenda] Erro ao carregar bloqueios: {e}")
        return set()


# ── Disponibilidade ──────────────────────────────────────────────────────────

def get_horarios_disponiveis(data_str: str) -> list:
    """
    Retorna lista de horários disponíveis em uma data específica.
    Considera: dia da semana ativo + bloqueios + agendamentos já existentes.
    """
    try:
        data_obj = date.fromisoformat(data_str)
    except ValueError:
        return []

    dia_semana = data_obj.weekday() + 1  # Python: 0=Seg→ ajusta para 1=Seg...6=Sab, 0=Dom
    # Converte: Python weekday 0=Seg→DB: 1=Seg, 6=Dom→DB: 0=Dom
    dia_db = (data_obj.weekday() + 1) % 7  # 0=Dom,1=Seg,...,6=Sab

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Verifica se o dia da semana está ativo
        cursor.execute(
            "SELECT ativo, horarios, max_por_dia FROM agenda_config WHERE dia_semana=%s",
            (dia_db,)
        )
        config = cursor.fetchone()
        if not config or not config['ativo']:
            cursor.close()
            conn.close()
            return []

        horarios_config = config.get('horarios') or []
        if isinstance(horarios_config, str):
            horarios_config = json.loads(horarios_config)
        max_por_dia = config.get('max_por_dia', 5)

        # Verifica se data está bloqueada
        cursor.execute("SELECT id FROM agenda_bloqueios WHERE data=%s", (data_str,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return []

        # Horários já ocupados nessa data (status não cancelado)
        cursor.execute("""
            SELECT hora FROM agendamentos
            WHERE data=%s AND status NOT IN ('cancelado')
        """, (data_str,))
        ocupados = {r['hora'] for r in cursor.fetchall()}

        # Total de agendamentos ativos no dia
        cursor.execute("""
            SELECT COUNT(*) AS n FROM agendamentos
            WHERE data=%s AND status NOT IN ('cancelado')
        """, (data_str,))
        total_dia = (cursor.fetchone() or {}).get('n', 0)

        cursor.close()
        conn.close()

        if total_dia >= max_por_dia:
            return []

        disponíveis = [h for h in horarios_config if h not in ocupados]
        return sorted(disponíveis)

    except Exception as e:
        print(f"[Agenda] Erro ao verificar disponibilidade de {data_str}: {e}")
        return []


def get_proximas_datas_disponiveis(quantidade: int = 5, dias_antecedencia: int = 1) -> list:
    """
    Retorna as próximas N datas com pelo menos 1 horário disponível.
    dias_antecedencia: mínimo de dias a partir de hoje.
    """
    resultado = []
    inicio = date.today() + timedelta(days=dias_antecedencia)
    max_busca = 60  # Não busca além de 60 dias

    for offset in range(max_busca):
        d = inicio + timedelta(days=offset)
        slots = get_horarios_disponiveis(str(d))
        if slots:
            resultado.append({
                'data': str(d),
                'data_br': d.strftime('%d/%m/%Y'),
                'dia_semana': DIAS_LABEL[(d.weekday() + 1) % 7],
                'dia_semana_abrev': DIAS_ABREV[(d.weekday() + 1) % 7],
                'horarios': slots,
            })
        if len(resultado) >= quantidade:
            break

    return resultado


# ── Agendamentos ─────────────────────────────────────────────────────────────

# ── Helper functions para WhatsApp e Agendamentos ─────────────────────────────

def _normalize_phone_number(phone_str: str) -> str:
    if not phone_str:
        return ""
    if '@c.us' in phone_str or '@lid' in phone_str:
        return phone_str
    import re
    digits = re.sub(r'\D', '', phone_str)
    if 10 <= len(digits) <= 15:
        if len(digits) == 10:  # Apenas número sem DDD
            digits = '55' + digits
        elif len(digits) == 11 and digits.startswith('0'):
            digits = digits[1:]
        if len(digits) in (10, 11) and not digits.startswith('55'):
            digits = '55' + digits
        return f"{digits}@c.us"
    return phone_str


def _get_or_create_session(user_id: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM chat_sessions WHERE user_id=%s", (user_id,))
    row = cursor.fetchone()
    if row:
        sess_id = row['id']
    else:
        cursor.execute("""
            INSERT INTO chat_sessions (user_id, created_at, updated_at, status, unread_count, ia_pausada, etapa_atual, kanban_stage)
            VALUES (%s, NOW(), NOW(), 'active', 0, 0, 1, 'atendimento_inicial')
        """, (user_id,))
        conn.commit()
        sess_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return sess_id


# ── Agendamentos ─────────────────────────────────────────────────────────────

def criar_agendamento(session_id: int, data_str: str, hora: str,
                      beneficio: str = '', nome_cliente: str = '',
                      telefone: str = '') -> dict:
    """
    Cria um novo agendamento se o horário estiver disponível, envia mensagem de confirmação
    via WhatsApp e agenda lembretes automáticos.
    """
    import os
    from datetime import datetime, timedelta
    from app.services.whatsapp_service import get_wpp_service
    from app.models.ai_model import _get_ai_setting

    disponiveis = get_horarios_disponiveis(data_str)
    if not disponiveis:
        return {'success': False, 'message': 'Nenhum horário disponível nesta data.'}
    if hora not in disponiveis:
        return {'success': False, 'message': f'Horário {hora} não disponível. Disponíveis: {", ".join(disponiveis)}'}

    # Normalização do telefone e resolução da sessão
    telefone_norm = _normalize_phone_number(telefone)
    if (not session_id or session_id == 0) and telefone_norm:
        session_id = _get_or_create_session(telefone_norm)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agendamentos
                (session_id, data, hora, beneficio, nome_cliente, telefone, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pendente')
        """, (session_id, data_str, hora, beneficio, nome_cliente, telefone_norm or telefone))
        conn.commit()
        new_id = cursor.lastrowid
        cursor.close()
        conn.close()

        # Envio de notificações e criação de lembretes
        if telefone_norm:
            wpp = get_wpp_service()
            session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
            
            # Formatação de data
            dt_obj = datetime.strptime(data_str, "%Y-%m-%d")
            data_br = dt_obj.strftime("%d/%m/%Y")
            
            # 1. Mensagem de confirmação imediata para o cliente
            msg_confirm = (
                f"Olá, {nome_cliente}! Seu agendamento de consulta com a Dra. Marina Marques foi realizado com sucesso. 📅\n\n"
                f"- *Assunto:* {beneficio or 'Consulta Geral'}\n"
                f"- *Data:* {data_br}\n"
                f"- *Horário:* {hora}\n\n"
                f"Esperamos por você! Se precisar reagendar ou cancelar, por favor nos avise com antecedência por aqui. 😊"
            )
            try:
                wpp.send_message(telefone_norm, msg_confirm, session_name=session_name)
                print(f"[Agenda] Confirmação de agendamento enviada para {telefone_norm}")
            except Exception as e_msg:
                print(f"[Agenda] Erro ao enviar mensagem de confirmação: {e_msg}")

            # 2. Agendamento de Lembretes do Cliente (24h e 2h antes)
            try:
                appointment_dt = datetime.strptime(f"{data_str} {hora}", "%Y-%m-%d %H:%M")
                now = datetime.now()

                # Lembrete 24 horas antes
                reminder_24h_dt = appointment_dt - timedelta(hours=24)
                if reminder_24h_dt > now:
                    msg_24h = (
                        f"Olá, {nome_cliente}! Passando para lembrar que você tem uma consulta com a Dra. Marina Marques amanhã. 📅\n\n"
                        f"- *Horário:* {hora}\n\n"
                        f"Até logo! Se tiver algum imprevisto, nos avise por aqui."
                    )
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO scheduled_followups (session_id, scheduled_at, message, sent)
                        VALUES (%s, %s, %s, 0)
                    """, (session_id, reminder_24h_dt.strftime("%Y-%m-%d %H:%M:%S"), msg_24h))
                    conn.commit()
                    cursor.close()
                    conn.close()

                # Lembrete 2 horas antes
                reminder_2h_dt = appointment_dt - timedelta(hours=2)
                if reminder_2h_dt > now:
                    msg_2h = (
                        f"Olá, {nome_cliente}! Lembrando que sua consulta com a Dra. Marina Marques está agendada para hoje, às {hora}. 📅\n\n"
                        f"Nos vemos em breve!"
                    )
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO scheduled_followups (session_id, scheduled_at, message, sent)
                        VALUES (%s, %s, %s, 0)
                    """, (session_id, reminder_2h_dt.strftime("%Y-%m-%d %H:%M:%S"), msg_2h))
                    conn.commit()
                    cursor.close()
                    conn.close()

            except Exception as e_rem:
                print(f"[Agenda] Erro ao agendar lembretes para o cliente: {e_rem}")

            # 3. Notificações do Administrador
            try:
                admin_phone = _get_ai_setting('admin_phone', '')
                if admin_phone:
                    admin_phone_norm = _normalize_phone_number(admin_phone)
                    if admin_phone_norm:
                        # Mensagem imediata de novo agendamento para o admin
                        msg_admin = (
                            f"🔔 *[NOVO AGENDAMENTO]*\n"
                            f"Um novo cliente agendou uma consulta pelo site.\n\n"
                            f"- *Cliente:* {nome_cliente}\n"
                            f"- *Telefone:* {telefone}\n"
                            f"- *Data:* {data_br}\n"
                            f"- *Horário:* {hora}\n"
                            f"- *Assunto:* {beneficio or 'Consulta Geral'}"
                        )
                        wpp.send_message(admin_phone_norm, msg_admin, session_name=session_name)

                        # Lembrete 2 horas antes para o admin (se ainda não passou)
                        if 'reminder_2h_dt' in locals() and reminder_2h_dt > now:
                            admin_session_id = _get_or_create_session('admin_notifications')
                            msg_admin_reminder = (
                                f"🔔 *[LEMBRETE DE CONSULTA]*\n"
                                f"Você tem uma consulta agendada hoje, às {hora}.\n\n"
                                f"- *Cliente:* {nome_cliente}\n"
                                f"- *Assunto:* {beneficio or 'Consulta Geral'}\n"
                                f"- *Telefone:* {telefone}"
                            )
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO scheduled_followups (session_id, scheduled_at, message, sent)
                                VALUES (%s, %s, %s, 0)
                            """, (admin_session_id, reminder_2h_dt.strftime("%Y-%m-%d %H:%M:%S"), msg_admin_reminder))
                            conn.commit()
                            cursor.close()
                            conn.close()
            except Exception as e_adm:
                print(f"[Agenda] Erro ao enviar alertas para o admin: {e_adm}")

        return {'success': True, 'id': new_id, 'message': 'Agendamento criado com sucesso.'}
    except Exception as e:
        print(f"[Agenda] Erro ao criar agendamento: {e}")
        return {'success': False, 'message': str(e)}


def atualizar_status(agendamento_id: int, status: str, observacoes: str = None) -> bool:
    """Atualiza o status de um agendamento."""
    valid = {'pendente', 'confirmado', 'cancelado', 'realizado'}
    if status not in valid:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if observacoes is not None:
            cursor.execute(
                "UPDATE agendamentos SET status=%s, observacoes=%s, updated_at=NOW() WHERE id=%s",
                (status, observacoes, agendamento_id)
            )
        else:
            cursor.execute(
                "UPDATE agendamentos SET status=%s, updated_at=NOW() WHERE id=%s",
                (status, agendamento_id)
            )
        conn.commit()
        cursor.close()
        conn.close()

        # Envia notificação via WhatsApp se o status foi confirmado ou cancelado
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM agendamentos WHERE id=%s", (agendamento_id,))
            agt = cursor.fetchone()
            cursor.close()
            conn.close()

            if agt and status in ('confirmado', 'cancelado'):
                telefone = agt.get('telefone')
                telefone_norm = _normalize_phone_number(telefone)
                if telefone_norm:
                    import os
                    from app.services.whatsapp_service import get_wpp_service
                    wpp = get_wpp_service()
                    session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
                    
                    data_br = agt['data'].strftime('%d/%m/%Y') if hasattr(agt['data'], 'strftime') else str(agt['data'])
                    hora = str(agt['hora'])[:5]
                    nome_cliente = agt.get('nome_cliente', 'Cliente')
                    
                    if status == 'confirmado':
                        msg = (
                            f"Olá, {nome_cliente}! Passando para avisar que sua consulta com a Dra. Marina Marques foi *confirmada*. 📅\n\n"
                            f"- *Data:* {data_br}\n"
                            f"- *Horário:* {hora}\n\n"
                            f"Esperamos você!"
                        )
                    else: # cancelado
                        msg = (
                            f"Olá, {nome_cliente}! Informamos que a sua consulta com a Dra. Marina Marques agendada para {data_br} às {hora} foi *cancelada*. ❌\n\n"
                            f"Se quiser realizar um novo agendamento, você pode usar nosso link ou solicitar um novo horário aqui pelo chat."
                        )
                    wpp.send_message(telefone_norm, msg, session_name=session_name)
                    print(f"[Agenda] Notificação de status '{status}' enviada para {telefone_norm}")
        except Exception as e_wpp:
            print(f"[Agenda] Erro ao enviar notificação de alteração de status: {e_wpp}")

        return True
    except Exception as e:
        print(f"[Agenda] Erro ao atualizar status: {e}")
        return False


def get_agendamentos(mes: int = None, ano: int = None, data_str: str = None,
                     session_id: int = None) -> list:
    """Retorna agendamentos com filtros opcionais."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conditions = []
        params = []
        if mes and ano:
            conditions.append("MONTH(a.data)=%s AND YEAR(a.data)=%s")
            params += [mes, ano]
        if data_str:
            conditions.append("a.data=%s")
            params.append(data_str)
        if session_id:
            conditions.append("a.session_id=%s")
            params.append(session_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cursor.execute(f"""
            SELECT a.*, cs.user_id,
                   MAX(CASE WHEN ud.key_name IN ('nome_completo','nome','nome_wpp')
                            THEN ud.value END) AS nome_db
            FROM agendamentos a
            LEFT JOIN chat_sessions cs ON cs.id = a.session_id
            LEFT JOIN user_data ud ON ud.session_id = a.session_id
            {where}
            GROUP BY a.id
            ORDER BY a.data ASC, a.hora ASC
        """, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        for row in rows:
            d = row.get('data')
            if d:
                row['data_br'] = d.strftime('%d/%m/%Y') if hasattr(d, 'strftime') else str(d)
                row['dia_semana'] = DIAS_LABEL[(d.weekday() + 1) % 7] if hasattr(d, 'weekday') else ''
            row['nome_display'] = row.get('nome_cliente') or row.get('nome_db') or 'Sem nome'
            row['status_label'] = STATUS_LABEL.get(row.get('status', 'pendente'), '')
        return rows
    except Exception as e:
        print(f"[Agenda] Erro ao listar agendamentos: {e}")
        return []


def get_agendamentos_por_data(mes: int, ano: int) -> dict:
    """Retorna dict {data_str: [agendamentos]} para renderizar calendário."""
    agts = get_agendamentos(mes=mes, ano=ano)
    resultado = {}
    for a in agts:
        key = str(a.get('data', ''))
        resultado.setdefault(key, []).append(a)
    return resultado


def get_agendamento_do_lead(session_id: int):
    """Retorna o próximo agendamento pendente/confirmado de um lead."""
    agts = get_agendamentos(session_id=session_id)
    hoje = str(date.today())
    futuros = [a for a in agts if str(a.get('data', '')) >= hoje
               and a.get('status') in ('pendente', 'confirmado')]
    return futuros[0] if futuros else None
