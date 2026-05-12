import json
import os
import time
from datetime import datetime
import mysql.connector
from app.config.database import get_db_connection

class ChatSession:
    """
    Classe para gerenciar sessões de chat com usuários
    """
    def __init__(self, user_id):
        """
        Inicializa uma sessão de chat para um usuário específico
        
        Args:
            user_id (str): ID único do usuário (número do WhatsApp)
        """
        self.user_id = user_id
        self.messages = []
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.user_data = {}
        self.status = "active"
        self.unread_count = 0
        self.last_message = ""
        self.session_id = None
        
        # Carrega sessão existente ou cria uma nova
        self._load_session()
    
    def _load_session(self):
        """
        Carrega uma sessão existente do banco de dados ou cria uma nova
        """
        try:
            # Conecta ao MySQL
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Busca sessão existente
            cursor.execute("SELECT * FROM chat_sessions WHERE user_id = %s", (self.user_id,))
            session_data = cursor.fetchone()
            
            if session_data:
                self.session_id = session_data['id']
                self.created_at = session_data['created_at']
                self.updated_at = session_data['updated_at']
                self.status = session_data['status']
                self.unread_count = session_data.get('unread_count', 0)
                self.last_message = session_data.get('last_message', "")
                
                # Carrega mensagens
                cursor.execute("SELECT * FROM chat_messages WHERE session_id = %s ORDER BY timestamp ASC", (self.session_id,))
                messages = cursor.fetchall()
                
                for msg in messages:
                    self.messages.append({
                        "role": msg['role'],
                        "content": msg['content'],
                        "timestamp": msg['timestamp']
                    })
                
                # Carrega dados do usuário
                cursor.execute("SELECT * FROM user_data WHERE session_id = %s", (self.session_id,))
                user_data = cursor.fetchall()
                
                for data in user_data:
                    self.user_data[data['key_name']] = data['value']
            else:
                # Se não existir, cria uma nova sessão no banco
                self.save()
            
            cursor.close()
            conn.close()
                
        except Exception as e:
            print(f"Erro ao carregar sessão: {e}")
            # Em caso de erro, continua com sessão em memória
    
    def add_message(self, role, content):
        """
        Adiciona uma mensagem ao histórico da conversa
        
        Args:
            role (str): Papel do remetente ('user' ou 'assistant')
            content (str): Conteúdo da mensagem
        """
        timestamp = datetime.now()
        message = {
            "role": role,
            "content": content,
            "timestamp": timestamp
        }
        self.messages.append(message)
        self.updated_at = datetime.now()
        self.last_message = content[:200]  # Armazena apenas o início
        
        if role == 'user':
            self.unread_count += 1
        else:
            self.unread_count = 0  # Reseta quando o bot ou admin responde
            
        # Se a sessão já está no banco, salva a mensagem diretamente e atualiza a sessão
        if self.session_id:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute(
                    "INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (%s, %s, %s, %s)",
                    (self.session_id, role, content, timestamp)
                )
                
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Erro ao salvar mensagem: {e}")
    
    def update_user_data(self, key, value):
        """
        Atualiza ou adiciona dados do usuário
        
        Args:
            key (str): Chave do dado
            value: Valor a ser armazenado
        """
        self.user_data[key] = value
        self.updated_at = datetime.now()
        
        # Se a sessão já está no banco, salva o dado diretamente
        if self.session_id:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # Verifica se o dado já existe
                cursor.execute(
                    "SELECT id FROM user_data WHERE session_id = %s AND key_name = %s",
                    (self.session_id, key)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # Atualiza o dado existente
                    cursor.execute(
                        "UPDATE user_data SET value = %s WHERE session_id = %s AND key_name = %s",
                        (str(value), self.session_id, key)
                    )
                else:
                    # Insere um novo dado
                    cursor.execute(
                        "INSERT INTO user_data (session_id, key_name, value) VALUES (%s, %s, %s)",
                        (self.session_id, key, str(value))
                    )
                
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Erro ao salvar dado do usuário: {e}")
    
    def get_conversation_history(self, max_messages=10):
        """
        Retorna o histórico de conversa formatado para a API da OpenAI

        Args:
            max_messages (int): Número máximo de mensagens a retornar

        Returns:
            list: Lista de mensagens formatadas
        """
        # Retorna as últimas N mensagens
        recent_messages = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages

        # Importa o prompt dinâmico (evita import circular no topo do arquivo)
        try:
            from app.models.ai_model import _get_system_prompt
            system_prompt = _get_system_prompt()
        except Exception:
            system_prompt = (
                "Você é um assistente virtual especializado em direito trabalhista. "
                "Seja cordial, profissional e preciso. Responda sempre em português."
            )

        formatted_messages = [
            {"role": "system", "content": system_prompt}
        ]

        # Adiciona as mensagens da conversa (filtra apenas roles válidos)
        for msg in recent_messages:
            role = msg.get("role") if isinstance(msg, dict) else msg["role"]
            content = msg.get("content") if isinstance(msg, dict) else msg["content"]
            if role in ("user", "assistant"):
                formatted_messages.append({"role": role, "content": content})

        return formatted_messages


    def save(self):
        """
        Salva a sessão atual no banco de dados
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            if self.session_id:
                # Atualiza a sessão existente
                cursor.execute(
                    "UPDATE chat_sessions SET updated_at = %s, status = %s, unread_count = %s, last_message = %s WHERE id = %s",
                    (self.updated_at, self.status, self.unread_count, self.last_message, self.session_id)
                )
            else:
                # Insere uma nova sessão
                cursor.execute(
                    "INSERT INTO chat_sessions (user_id, created_at, updated_at, status, unread_count, last_message) VALUES (%s, %s, %s, %s, %s, %s)",
                    (self.user_id, self.created_at, self.updated_at, self.status, self.unread_count, self.last_message)
                )
                
                # Obtém o ID da sessão inserida
                self.session_id = cursor.lastrowid
                
                # Insere as mensagens existentes
                for msg in self.messages:
                    cursor.execute(
                        "INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (%s, %s, %s, %s)",
                        (self.session_id, msg["role"], msg["content"], msg["timestamp"])
                    )
                
                # Insere os dados do usuário existentes
                for key, value in self.user_data.items():
                    cursor.execute(
                        "INSERT INTO user_data (session_id, key_name, value) VALUES (%s, %s, %s)",
                        (self.session_id, key, str(value))
                    )
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Erro ao salvar sessão: {e}")
    
    def close(self):
        """
        Marca a sessão como concluída
        """
        self.status = "closed"
        self.updated_at = datetime.now()
        self.save()
    
    def mark_as_read(self):
        """
        Marca todas as mensagens como lidas (zera o contador de não lidas)
        """
        self.unread_count = 0
        self.updated_at = datetime.now()
        self.save()
    
    @staticmethod
    def get_all_sessions(status=None):
        """
        Retorna todas as sessões de chat
        
        Args:
            status (str, optional): Filtrar por status ('active', 'closed')
            
        Returns:
            list: Lista de sessões com suas mensagens e dados
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Define a consulta SQL
            query = "SELECT * FROM chat_sessions"
            params = []
            
            if status:
                query += " WHERE status = %s"
                params.append(status)
            
            # Busca as sessões
            cursor.execute(query, params)
            sessions = cursor.fetchall()
            
            # Para cada sessão, busca mensagens e dados do usuário
            result = []
            for session in sessions:
                session_id = session['id']
                
                # Busca mensagens
                cursor.execute("SELECT * FROM chat_messages WHERE session_id = %s ORDER BY timestamp ASC", (session_id,))
                messages = cursor.fetchall()
                
                # Busca dados do usuário
                cursor.execute("SELECT * FROM user_data WHERE session_id = %s", (session_id,))
                user_data = cursor.fetchall()
                
                # Formata os dados do usuário
                user_data_dict = {}
                for data in user_data:
                    user_data_dict[data['key_name']] = data['value']
                
                # Adiciona mensagens e dados do usuário à sessão
                session['messages'] = messages
                session['user_data'] = user_data_dict
                
                result.append(session)
            
            cursor.close()
            conn.close()
            
            return result
            
        except Exception as e:
            print(f"Erro ao buscar sessões: {e}")
            return []

    @staticmethod
    def get_session(session_id):
        """
        Busca uma sessão específica pelo ID
        
        Args:
            session_id (int): ID da sessão
            
        Returns:
            dict: Sessão com suas mensagens e dados do usuário, ou None se não encontrada
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Busca a sessão
            cursor.execute("SELECT * FROM chat_sessions WHERE id = %s", (session_id,))
            session = cursor.fetchone()
            
            if not session:
                return None
            
            # Busca mensagens
            cursor.execute("SELECT * FROM chat_messages WHERE session_id = %s ORDER BY timestamp ASC", (session_id,))
            messages = cursor.fetchall()
            
            # Busca dados do usuário
            cursor.execute("SELECT * FROM user_data WHERE session_id = %s", (session_id,))
            user_data = cursor.fetchall()
            
            # Formata os dados do usuário
            user_data_dict = {}
            for data in user_data:
                user_data_dict[data['key_name']] = data['value']
            
            # Adiciona mensagens e dados do usuário à sessão
            session['messages'] = messages
            session['user_data'] = user_data_dict
            
            cursor.close()
            conn.close()
            
            return session
            
        except Exception as e:
            print(f"Erro ao buscar sessão: {e}")
            return None
