import os
from datetime import datetime
from app.config.database import get_db_connection


class WhatsAppConfig:
    """Model para gerenciar a configuração da conexão WhatsApp via WPP Connect."""

    @staticmethod
    def get_config(session_name=None):
        """Retorna a configuração atual do WhatsApp pelo nome da sessão."""
        if session_name is None:
            session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM whatsapp_config WHERE session_name = %s",
                (session_name,)
            )
            config = cursor.fetchone()
            cursor.close()
            conn.close()
            return config
        except Exception as e:
            print(f"[WhatsAppConfig] Erro ao buscar config: {e}")
            return None

    @staticmethod
    def save_config(session_name, phone_number=None, token=None, status=None):
        """Salva ou atualiza a configuração da sessão WhatsApp."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            now = datetime.now()

            cursor.execute(
                "SELECT id FROM whatsapp_config WHERE session_name = %s",
                (session_name,)
            )
            existing = cursor.fetchone()

            if existing:
                fields = ["updated_at = %s"]
                values = [now]
                if phone_number is not None:
                    fields.append("phone_number = %s")
                    values.append(phone_number)
                if token is not None:
                    fields.append("token = %s")
                    values.append(token)
                if status is not None:
                    fields.append("status = %s")
                    values.append(status)
                values.append(session_name)
                cursor.execute(
                    f"UPDATE whatsapp_config SET {', '.join(fields)} WHERE session_name = %s",
                    values
                )
            else:
                cursor.execute(
                    """INSERT INTO whatsapp_config
                       (session_name, phone_number, token, status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (session_name, phone_number, token,
                     status or 'disconnected', now, now)
                )

            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            print(f"[WhatsAppConfig] Erro ao salvar config: {e}")
            return False

    @staticmethod
    def get_all():
        """Retorna todas as sessões configuradas."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM whatsapp_config ORDER BY updated_at DESC")
            configs = cursor.fetchall()
            cursor.close()
            conn.close()
            return configs
        except Exception as e:
            print(f"[WhatsAppConfig] Erro ao listar configs: {e}")
            return []
