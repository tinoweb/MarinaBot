import os
import requests
import re
from app.models.whatsapp_model import WhatsAppConfig


class WhatsAppAPIService:
    """
    Serviço de comunicação com o WPP Connect Server via REST API.
    O servidor WPP Connect roda como container Docker separado (:21465)
    e gerencia a sessão/QR code do WhatsApp Web.
    """

    def __init__(self):
        self.server_url = os.getenv('WPP_SERVER_URL', 'http://wppconnect:21465')
        self.secret_key = os.getenv('WPP_SECRET_KEY', 'marina_bot_secret')
        self.session_name = os.getenv('WHATSAPP_SESSION', 'marina_bot_session')
        self.app_url = os.getenv('APP_URL', 'http://app:5000')
        self._token = None

    def _get_token(self):
        """Retorna o token armazenado (memória ou banco de dados)."""
        if self._token:
            return self._token
        config = WhatsAppConfig.get_config(self.session_name)
        if config and config.get('token'):
            self._token = config['token']
        return self._token

    def _ensure_token(self, session_name=None):
        """
        Garante que temos um token válido.
        Se não houver token, gera um novo automaticamente.
        Retorna True se tem token, False se falhou.
        """
        session = session_name or self.session_name
        token = self._get_token()
        if not token:
            print(f"[WPP] Token ausente para sessão '{session}'. Gerando automaticamente...")
            token = self.generate_token(session)
        return bool(token)

    def _headers(self, session_name=None):
        """Monta os headers de autenticação para a API do WPP Connect."""
        session = session_name or self.session_name
        self._ensure_token(session)
        token = self._get_token()
        if not token:
            print(f"[WPP] AVISO: Sem token para sessão '{session}'. Chamada pode falhar com 401.")
            return {}
        return {'Authorization': f'Bearer {token}'}

    def generate_token(self, session_name=None):
        """Gera um token de acesso para a sessão no WPP Connect Server."""
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/{self.secret_key}/generate-token"
        try:
            resp = requests.post(url, timeout=15)
            print(f"[WPP] generate-token status={resp.status_code} url={url}")
            print(f"[WPP] generate-token body={resp.text[:300]}")
            resp.raise_for_status()
            data = resp.json()
            token = data.get('token')
            if token:
                self._token = token
                WhatsAppConfig.save_config(
                    session_name=session,
                    token=token,
                    status='token_generated'
                )
                print(f"[WPP] Token gerado para sessão '{session}'")
            return token
        except Exception as e:
            print(f"[WPP] Erro ao gerar token: {e}")
            return None

    def start_session(self, session_name=None):
        """Inicia a sessão no WPP Connect Server com webhook apontando para o Flask."""
        session = session_name or self.session_name
        # Garante que temos token antes de iniciar
        self._ensure_token(session)

        # A URL do webhook deve ser acessível pelo container do WPP Connect.
        # Dentro do Docker, 'app' resolve para o IP do container da nossa app Flask.
        webhook_url = f"{self.app_url}/webhook/wppconnect"
        
        print(f"[WPP] Iniciando sessão '{session}' com Webhook: {webhook_url}")
        print(f"[WPP] APP_URL configurado: {self.app_url}")
        print(f"[WPP] WPP Server URL: {self.server_url}")
        
        url = f"{self.server_url}/api/{session}/start-session"
        payload = {
            "webhook": webhook_url,
            "waitForLogin": False,
            "autoClose": 0,  # 0 = nunca fecha automaticamente
            "headless": True
        }
        try:
            print(f"[WPP] Enviando payload para start-session: {payload}")
            resp = requests.post(url, json=payload, headers=self._headers(session), timeout=30)
            print(f"[WPP] Status code: {resp.status_code}")
            data = resp.json()
            print(f"[WPP] start-session resposta: {data}")
            WhatsAppConfig.save_config(session_name=session, status='starting')
            return data
        except Exception as e:
            print(f"[WPP] Erro ao iniciar sessão: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_qrcode(self, session_name=None):
        """Retorna o QR code da sessão em formato base64."""
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/qrcode-session"
        try:
            resp = requests.get(url, headers=self._headers(session), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('qrcode') or data.get('base64Qrcode')
            return None
        except Exception as e:
            print(f"[WPP] Erro ao obter QR code: {e}")
            return None

    def get_status(self, session_name=None):
        """Retorna o status atual da sessão no servidor WPP Connect."""
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/status-session"
        try:
            resp = requests.get(url, headers=self._headers(session), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return {'status': 'error', 'message': f'HTTP {resp.status_code}'}
        except requests.exceptions.ConnectionError:
            return {'status': 'unreachable', 'message': 'Servidor WPP Connect indisponível'}
        except Exception as e:
            print(f"[WPP] Erro ao verificar status: {e}")
            return {'status': 'error', 'message': str(e)}

    def close_session(self, session_name=None):
        """Encerra a sessão e limpa o token."""
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/close-session"
        try:
            resp = requests.post(url, headers=self._headers(session), timeout=15)
            data = resp.json()
            WhatsAppConfig.save_config(session_name=session, status='disconnected', token='')
            self._token = None
            print(f"[WPP] Sessão '{session}' encerrada")
            return data
        except Exception as e:
            print(f"[WPP] Erro ao fechar sessão: {e}")
            return None

    def get_contact(self, contact_id, session_name=None):
        """Obtém detalhes de um contato (útil para resolver @lid para @c.us)."""
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/contact/{contact_id}"
        try:
            resp = requests.get(url, headers=self._headers(session), timeout=10)
            print(f"[WPP] get_contact({contact_id}): status={resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"[WPP] get_contact({contact_id}) response: {data}")
                return data
            return None
        except Exception as e:
            print(f"[WPP] Erro ao obter contato {contact_id}: {e}")
            return None

    def get_all_contacts(self, session_name=None):
        """Obtém todos os contatos da sessão (útil para resolver @lid)."""
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/all-contacts"
        try:
            resp = requests.get(url, headers=self._headers(session), timeout=15)
            print(f"[WPP] get_all_contacts: status={resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                contacts = data.get('response', data.get('contacts', []))
                print(f"[WPP] get_all_contacts: encontrados {len(contacts) if isinstance(contacts, list) else 'N/A'} contatos")
                return contacts
            return None
        except Exception as e:
            print(f"[WPP] Erro ao obter todos os contatos: {e}")
            return None

    def resolve_phone_id(self, contact_id, session_name=None):
        """
        Tenta descobrir o número real (@c.us) a partir de um ID (como @lid).
        Retorna o ID formatado como @c.us ou None.
        """
        if not contact_id:
            return None

        # Se já é um número @c.us, apenas retorna
        if '@c.us' in contact_id or '@s.whatsapp.net' in contact_id:
            return contact_id.replace('@s.whatsapp.net', '@c.us')

        print(f"[WPP] Tentando resolver ID: {contact_id}")

        # Estratégia 1: get_contact (confiável para resolver LIDs)
        data = self.get_contact(contact_id, session_name)
        if data and data.get('status') == 'success':
            resp_data = data.get('response')
            if resp_data and isinstance(resp_data, dict):
                # Alguns servidores retornam o número em 'pushname' ou 'number' ou no próprio 'id'
                # Mas o mais confiável é ver se o ID retornado é diferente do ID solicitado
                res_id = resp_data.get('id', {}).get('_serialized') or resp_data.get('id')
                if res_id and ('@c.us' in res_id or '@s.whatsapp.net' in res_id):
                    resolved = res_id.replace('@s.whatsapp.net', '@c.us')
                    print(f"[WPP] ID resolvido: {resolved}")
                    return resolved

        # Estratégia 2: Tentar extrair do formattedName ou pushname
        if resp_data and isinstance(resp_data, dict):
            formatted_name = resp_data.get('formattedName', '') or resp_data.get('pushname', '')
            if formatted_name:
                import re
                # Procura por padrões de número de telefone específicos
                phone_patterns = [
                    r'\+?(\d{2}\s?\d{2}\s?\d{4,5}[-\s]?\d{4})',  # +55 XX XXXXX-XXXX
                    r'(\d{10,11})',  # Apenas 10-11 dígitos consecutivos
                    r'\((\d{2})\)\s*(\d{4,5}[-\s]?\d{4})',  # (55) XXXXX-XXXX
                ]
                
                for pattern in phone_patterns:
                    phone_match = re.search(pattern, formatted_name)
                    if phone_match:
                        # Para o padrão com parênteses, precisamos juntar os grupos
                        if '(' in pattern:
                            groups = phone_match.groups()
                            phone_digits = ''.join(filter(None, groups))
                        else:
                            phone_digits = re.sub(r'[^\d]', '', phone_match.group(1))
                        
                        if 10 <= len(phone_digits) <= 15:
                            # Garante que comece com código do país se não tiver
                            if len(phone_digits) == 10:  # Apenas número sem DDD
                                phone_digits = '55' + phone_digits  # Assume Brasil
                            elif len(phone_digits) == 11 and phone_digits.startswith('0'):  # 0XX XXXXXXXX
                                phone_digits = phone_digits[1:]  # Remove o zero inicial
                            
                            resolved = f"{phone_digits}@c.us"
                            print(f"[WPP] Número extraído do formattedName: {formatted_name} -> {resolved}")
                            return resolved

        # Estratégia 3: Tentar get_all_contacts para buscar o contato
        try:
            all_contacts = self.get_all_contacts(session_name)
            if all_contacts and isinstance(all_contacts, list):
                for contact in all_contacts:
                    if isinstance(contact, dict):
                        contact_id_field = contact.get('id', {}).get('_serialized') or contact.get('id')
                        if contact_id_field == contact_id:
                            # Encontrou o contato, agora tenta extrair o número
                            contact_phone = contact.get('number') or contact.get('phone')
                            if contact_phone:
                                phone_digits = re.sub(r'[^\d]', '', contact_phone)
                                if len(phone_digits) >= 10:
                                    resolved = f"{phone_digits}@c.us"
                                    print(f"[WPP] Número encontrado via get_all_contacts: {resolved}")
                                    return resolved
        except Exception as e:
            print(f"[WPP] Erro ao buscar todos os contatos: {e}")

        print(f"[WPP] Não foi possível resolver o ID {contact_id}")
        return None

    def check_number_status(self, phone, session_name=None):
        """
        Verifica se um número existe no WhatsApp via WPP Connect.
        phone deve ser apenas os dígitos (ex: '5519989033412').
        Retorna dict com status ou None em caso de erro.
        """
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/check-number-status/{phone}"
        try:
            resp = requests.get(url, headers=self._headers(session), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                print(f"[WPP] check-number-status({phone}): {data}")
                return data.get('response', {})
            return None
        except Exception as e:
            print(f"[WPP] Erro ao verificar número {phone}: {e}")
            return None

    def send_message(self, phone, message, session_name=None):
        """Envia uma mensagem de texto para um número via WPP Connect."""
        session = session_name or self.session_name
        url_send = f"{self.server_url}/api/{session}/send-message"
        
        # Lista de tentativas com diferentes formatos de ID
        attempts = []
        
        if '@c.us' in phone or '@s.whatsapp.net' in phone:
            # Número real: tenta chatId @c.us, depois @s.whatsapp.net, depois digits
            attempts = [
                (url_send, {"chatId": phone, "message": message, "isGroup": False}),
                (url_send, {"chatId": phone.replace('@c.us', '@s.whatsapp.net'), "message": message, "isGroup": False}),
                (url_send, {"phone": [phone.split('@')[0]], "message": message, "isGroup": False})
            ]
        elif '@lid' in phone:
            # IDs @lid: o WPP Connect não consegue enviar diretamente para @lid
            # sem um número real associado. Retorna erro imediatamente.
            print(f"[WPP] ERRO: Não é possível enviar para ID @lid sem número real (@c.us).")
            print(f"[WPP] Configure o 'Telefone Real' na página da conversa no painel admin.")
            return {
                "status": "error",
                "message": "Não é possível enviar para este contato (@lid) sem o número de telefone real. "
                           "Configure o campo 'Telefone Real' no painel da conversa."
            }
        else:
            # Apenas números: tenta phone field, depois chatId @c.us
            attempts = [
                (url_send, {"phone": [phone], "message": message, "isGroup": False}),
                (url_send, {"chatId": f"{phone}@c.us", "message": message, "isGroup": False})
            ]

        last_error_message = None
        headers = self._headers(session)
        for url, payload in attempts:
            try:
                first_key = list(payload.keys())[0]
                first_val = str(list(payload.values())[0])[:40]
                print(f"[WPP] Tentando {url.split('/')[-1]}({first_key}={first_val}) na sessão {session}...")
                resp = requests.post(url, json=payload, headers=headers, timeout=20)
                print(f"[WPP] Resposta HTTP {resp.status_code}: {resp.text[:200]}")

                # Tenta parsear como JSON; o WPP Connect às vezes retorna string pura
                try:
                    data = resp.json()
                except Exception:
                    data = {"status": "error", "message": resp.text}

                # Normaliza: se data não é dict (ex: é string), envolve num dict
                if not isinstance(data, dict):
                    data = {"status": "error", "message": str(data)}

                if resp.status_code in (200, 201):
                    if data.get('status') == 'success':
                        print(f"[WPP] ✓ Mensagem aceita para envio via {url.split('/')[-1]}")
                        return data
                elif resp.status_code == 401:
                    print(f"[WPP] Token inválido (401). Gerando novo token...")
                    self._token = None
                    new_token = self.generate_token(session)
                    if new_token:
                        headers = self._headers(session)
                    last_error_message = "Token inválido"
                    continue

                # Detecta erro explícito
                msg = str(data.get('message', ''))
                last_error_message = msg or f"HTTP {resp.status_code}"
                if data.get('status') == 'error' or 'não existe' in msg or 'does not exist' in msg.lower():
                    print(f"[WPP] Erro explícito do servidor: {msg}")
                    continue

            except Exception as e:
                print(f"[WPP] Erro na tentativa com {url}: {e}")
                last_error_message = str(e)
                continue

        print(f"[WPP] Todas as tentativas falharam para {phone}")
        return {"status": "error", "message": last_error_message or "Falha em todas as tentativas de entrega"}

    def send_reply(self, chat_id, message, quoted_message_id, session_name=None):
        """
        Envia uma resposta citando uma mensagem anterior.
        Útil para responder IDs @lid quando o envio direto falha.
        """
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/send-reply"
        payload = {
            "chatId": chat_id,
            "message": message,
            "quotedMessageId": quoted_message_id
        }
        try:
            print(f"[WPP] send-reply para {chat_id} citando {quoted_message_id}...")
            resp = requests.post(url, json=payload, headers=self._headers(session), timeout=20)
            print(f"[WPP] send-reply resposta HTTP {resp.status_code}: {resp.text[:200]}")
            # Trata resposta string pura (não-dict)
            try:
                data = resp.json()
            except Exception:
                return {"status": "error", "message": resp.text}
            if not isinstance(data, dict):
                return {"status": "error", "message": str(data)}
            return data
        except Exception as e:
            print(f"[WPP] Erro ao enviar send-reply: {e}")
            return {"status": "error", "message": str(e)}

    def logout_session(self, session_name=None):
        """Faz logout da sessão (desvincula o dispositivo)."""
        session = session_name or self.session_name
        url = f"{self.server_url}/api/{session}/logout-session"
        try:
            resp = requests.post(url, headers=self._headers(session), timeout=15)
            WhatsAppConfig.save_config(session_name=session, status='disconnected', token='')
            self._token = None
            return resp.json()
        except Exception as e:
            print(f"[WPP] Erro ao fazer logout: {e}")
            return None


_wpp_service = None


def get_wpp_service():
    """Retorna a instância global do serviço WPP Connect."""
    global _wpp_service
    if _wpp_service is None:
        _wpp_service = WhatsAppAPIService()
    return _wpp_service
