import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(timezone='America/Sao_Paulo')
    return _scheduler


def start_scheduler():
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.add_job(
            _check_followups,
            'interval',
            minutes=5,
            id='followup_check',
            replace_existing=True,
            max_instances=1
        )
        scheduler.add_job(
            _send_scheduled_followups,
            'interval',
            minutes=1,
            id='scheduled_followup_send',
            replace_existing=True,
            max_instances=1
        )
        scheduler.start()
        logger.info("[Scheduler] Follow-up scheduler iniciado.")


def stop_scheduler():
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)


def restart_scheduler():
    global _scheduler
    stop_scheduler()
    _scheduler = None
    start_scheduler()
    logger.info("[Scheduler] Scheduler reiniciado via painel admin.")


def _check_followups():
    """Verifica e envia follow-ups automáticos para conversas inativas (Etapas 10 e 11)."""
    try:
        from app.models.ai_model import _get_ai_setting
        followup_enabled = _get_ai_setting('followup_enabled', 'true')
        if followup_enabled.lower() != 'true':
            return

        from app.config.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        twenty_four_hours_ago = now - timedelta(hours=24)

        cursor.execute("""
            SELECT cs.id, cs.user_id, cs.qualificacao,
                   cs.ultimo_contato_at, cs.etapa_atual,
                   ud_followup.value AS followup_enviado,
                   ud_phone.value    AS real_phone,
                   ud_parto.value    AS situacao_parto
            FROM chat_sessions cs
            LEFT JOIN user_data ud_followup ON ud_followup.session_id = cs.id
                   AND ud_followup.key_name = 'followup_enviado'
            LEFT JOIN user_data ud_phone    ON ud_phone.session_id    = cs.id
                   AND ud_phone.key_name    = 'real_phone'
            LEFT JOIN user_data ud_parto    ON ud_parto.session_id    = cs.id
                   AND ud_parto.key_name    = 'situacao_parto'
            WHERE cs.status = 'active'
              AND cs.ia_pausada = 0
              AND cs.ultimo_contato_at IS NOT NULL
              AND cs.ultimo_contato_at < %s
              AND (ud_followup.value IS NULL OR ud_followup.value IN ('0', '1'))
        """, (one_hour_ago,))

        sessions = cursor.fetchall()
        cursor.close()
        conn.close()

        if not sessions:
            return

        from app.services.whatsapp_service import get_wpp_service
        wpp = get_wpp_service()
        session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')

        for sess in sessions:
            try:
                _send_followup(sess, wpp, session_name, now, one_hour_ago, twenty_four_hours_ago)
            except Exception as e:
                logger.error(f"[Scheduler] Erro ao processar follow-up para {sess.get('user_id')}: {e}")

    except Exception as e:
        logger.error(f"[Scheduler] Erro geral no check_followups: {e}")
        import traceback
        traceback.print_exc()


def _send_followup(sess, wpp, session_name, now, one_hour_ago, twenty_four_hours_ago):
    from app.models.chat_model import ChatSession

    user_id = sess['user_id']
    ultimo_contato = sess.get('ultimo_contato_at')
    followup_enviado = sess.get('followup_enviado') or '0'
    situacao_parto = sess.get('situacao_parto') or ''
    real_phone = sess.get('real_phone')
    target_id = real_phone if real_phone else user_id

    chat_session = ChatSession(user_id)

    # ── Etapa 10 — 1 hora sem resposta ──────────────────────────────────────
    if followup_enviado == '0' and ultimo_contato < one_hour_ago:
        msg = (
            "Oi! Tudo bem por aí?\n\n"
            "Vi que nossa conversa ficou por aqui. Queria saber se ficou "
            "alguma dúvida que posso ajudar. 😊\n\n"
            "Estou à disposição!"
        )
        result = wpp.send_message(target_id, msg, session_name=session_name)
        if isinstance(result, dict) and result.get('status') == 'success':
            chat_session.add_message('assistant', msg)
            chat_session.update_user_data('followup_enviado', '1')
            chat_session.update_user_data('followup_1h_at', now.isoformat())
            chat_session.save()
            logger.info(f"[Scheduler] Follow-up 1h enviado para {user_id}")

    # ── Etapa 11 — 24 horas sem resposta ────────────────────────────────────
    elif followup_enviado == '1' and ultimo_contato < twenty_four_hours_ago:
        if situacao_parto == 'bebe_nasceu':
            msg = (
                "O prazo para garantir o benefício vai até o dia 15 do mês seguinte "
                "ao nascimento.\n\n"
                "A Dra. Marina ainda consegue analisar — mas precisa ser agora.\n\n"
                "Quer que eu encaminhe? ✅"
            )
        else:
            msg = (
                "Olá! Passando para lembrar que o Salário Maternidade tem prazo.\n\n"
                "Quanto mais perto do parto, menos tempo para garantir o benefício "
                "com segurança.\n\n"
                "A Dra. Marina ainda consegue analisar o seu caso — mas o ideal é "
                "agir agora. ✅\n\n"
                "Quer que eu encaminhe para ela?"
            )
        result = wpp.send_message(target_id, msg, session_name=session_name)
        if isinstance(result, dict) and result.get('status') == 'success':
            chat_session.add_message('assistant', msg)
            chat_session.update_user_data('followup_enviado', '2')
            chat_session.update_user_data('followup_24h_at', now.isoformat())
            chat_session.save()
            logger.info(f"[Scheduler] Follow-up 24h enviado para {user_id}")


def _send_scheduled_followups():
    """Processa follow-ups agendados manualmente pelo admin."""
    try:
        from app.config.database import get_db_connection
        from app.services.whatsapp_service import WhatsappService
        import os as _os

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT sf.id, sf.session_id, sf.message, cs.user_id "
            "FROM scheduled_followups sf "
            "JOIN chat_sessions cs ON cs.id = sf.session_id "
            "WHERE sf.sent = 0 AND sf.scheduled_at <= NOW()"
        )
        pending = cur.fetchall()
        cur.close()
        conn.close()

        if not pending:
            return

        session_name = _os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
        wpp = WhatsappService()

        for row in pending:
            try:
                user_id = row['user_id']
                msg = row['message']
                is_lid = '@lid' in user_id
                result = wpp.send_message(user_id, msg, session_name=session_name, is_lid=is_lid)
                if isinstance(result, dict) and result.get('status') == 'success':
                    conn2 = get_db_connection()
                    cur2 = conn2.cursor()
                    cur2.execute("UPDATE scheduled_followups SET sent = 1 WHERE id = %s", (row['id'],))
                    conn2.commit()
                    cur2.close()
                    conn2.close()
                    logger.info(f"[Scheduler] Follow-up agendado #{row['id']} enviado para {user_id}")
            except Exception as ex:
                logger.error(f"[Scheduler] Erro no follow-up agendado #{row['id']}: {ex}")
    except Exception as e:
        logger.error(f"[Scheduler] Erro em _send_scheduled_followups: {e}")
