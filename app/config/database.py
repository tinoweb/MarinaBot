import os
import mysql.connector
from dotenv import load_dotenv

# Carrega as variáveis de ambiente
load_dotenv()

def get_db_connection():
    """
    Cria e retorna uma conexão com o banco de dados MySQL
    
    Returns:
        connection: Objeto de conexão com o MySQL
    """
    try:
        connection = mysql.connector.connect(
            host=os.getenv('MYSQL_HOST', 'localhost'),
            user=os.getenv('MYSQL_USER', 'root'),
            password=os.getenv('MYSQL_PASSWORD', ''),
            database=os.getenv('MYSQL_DB', 'jusbot'),
            port=int(os.getenv('MYSQL_PORT', 3306))
        )
        return connection
    except mysql.connector.Error as err:
        print(f"Erro ao conectar ao MySQL: {err}")
        raise

def init_db():
    """
    Inicializa o banco de dados criando as tabelas necessárias se não existirem
    """
    try:
        # Obtém conexão com o banco
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Cria tabela de sessões de chat
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(200) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            unread_count INT NOT NULL DEFAULT 0,
            last_message TEXT,
            UNIQUE KEY (user_id)
        )
        ''')
        
        # Altera o tamanho do user_id caso já exista a tabela com VARCHAR menor
        try:
            cursor.execute('''
            ALTER TABLE chat_sessions MODIFY COLUMN user_id VARCHAR(200) NOT NULL
            ''')
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN unread_count INT NOT NULL DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN last_message TEXT")
        except Exception:
            pass

        # Colunas profissionais para gestão de atendimento
        try:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN ia_pausada TINYINT(1) NOT NULL DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN qualificacao VARCHAR(50) DEFAULT NULL")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN etapa_atual TINYINT NOT NULL DEFAULT 1")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN ultimo_contato_at DATETIME DEFAULT NULL")
        except Exception:
            pass

        
        # Cria tabela de mensagens
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        )
        ''')
        
        # Cria tabela de dados do usuário
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_data (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            key_name VARCHAR(50) NOT NULL,
            value TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
            UNIQUE KEY (session_id, key_name)
        )
        ''')
        
        # Cria tabela de configuração da conexão WhatsApp
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS whatsapp_config (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_name VARCHAR(100) NOT NULL,
            phone_number VARCHAR(30),
            token TEXT,
            status VARCHAR(30) NOT NULL DEFAULT 'disconnected',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            UNIQUE KEY (session_name)
        )
        ''')

        # Notas internas por conversa
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_notes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            note TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_notes_session (session_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        # Checklist de documentos por conversa
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_checklist (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            doc_type VARCHAR(60) NOT NULL,
            checked TINYINT(1) DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_checklist (session_id, doc_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        # Follow-ups agendados manualmente
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_followups (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            scheduled_at DATETIME NOT NULL,
            message TEXT NOT NULL,
            sent TINYINT(1) DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_sf_session (session_id),
            INDEX idx_sf_scheduled (scheduled_at, sent)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        # Uso de tokens da OpenAI por conversa
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS token_usage (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT,
            model VARCHAR(60),
            prompt_tokens INT DEFAULT 0,
            completion_tokens INT DEFAULT 0,
            total_tokens INT DEFAULT 0,
            estimated_cost_usd DECIMAL(10,6) DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_usage_created (created_at),
            INDEX idx_usage_session (session_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        # Cria tabela de configurações da IA
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            setting_key VARCHAR(100) NOT NULL,
            setting_value TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT NOW(),
            updated_at DATETIME NOT NULL DEFAULT NOW() ON UPDATE NOW(),
            UNIQUE KEY (setting_key)
        )
        ''')

        # Carrega o script real da Dra. Marina como prompt padrão
        try:
            import os as _os
            _script_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), 'modelo_atendimento_ia.txt')
            with open(_script_path, 'r', encoding='utf-8') as _f:
                _default_prompt = _f.read()
        except Exception:
            _default_prompt = (
                'Você é a assistente virtual da Dra. Marina Marques, advogada especialista em '
                'Salário Maternidade pelo INSS. Atenda com tom acolhedor, simples e direto. '
                'Uma pergunta por vez. Nunca negocie honorários. Nunca dê detalhes técnicos '
                'antes do contrato assinado. Responda sempre em português.'
            )

        cursor.execute('''
        INSERT IGNORE INTO ai_settings (setting_key, setting_value)
        VALUES ('system_prompt', %s)
        ''', (_default_prompt,))

        # Configurações adicionais padrão
        defaults_extra = [
            ('instagram_handle', '@drainss'),
            ('followup_enabled', 'true'),
            ('bot_name', 'Assistente da Dra. Marina'),
            ('welcome_message', 'Olá! Aqui é a assistente da Dra. Marina Marques, advogada especialista em benefícios do INSS.\n\nA Dra. Marina já recebeu seu contato. 👩‍⚖️\n\nMe conta: com qual benefício posso te ajudar hoje?'),
            ('ai_model', 'gpt-4o-mini'),
            ('temperature', '0.4'),
        ]
        for _key, _val in defaults_extra:
            cursor.execute('''
            INSERT IGNORE INTO ai_settings (setting_key, setting_value) VALUES (%s, %s)
            ''', (_key, _val))

        conn.commit()
        cursor.close()
        conn.close()
        
        print("Banco de dados inicializado com sucesso!")
        
    except mysql.connector.Error as err:
        print(f"Erro ao inicializar o banco de dados: {err}")
        raise
