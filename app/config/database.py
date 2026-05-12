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

        # Insere prompt padrão se não existir
        cursor.execute('''
        INSERT IGNORE INTO ai_settings (setting_key, setting_value)
        VALUES ('system_prompt', 'Você é um assistente jurídico especializado em direito trabalhista, chamado Marina Bot. Seu objetivo é coletar informações relevantes para casos trabalhistas e ajudar clientes a entenderem seus direitos. Seja cordial, profissional e preciso. Responda sempre em português.')
        ''')

        conn.commit()
        cursor.close()
        conn.close()
        
        print("Banco de dados inicializado com sucesso!")
        
    except mysql.connector.Error as err:
        print(f"Erro ao inicializar o banco de dados: {err}")
        raise
