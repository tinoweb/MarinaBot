import os
import base64
import tempfile
import requests

SUPPORTED_AUDIO_TYPES = ('ptt', 'audio', 'voice')

AUDIO_MIME_TO_EXT = {
    'audio/ogg': '.ogg',
    'audio/ogg; codecs=opus': '.ogg',
    'audio/opus': '.ogg',
    'audio/mp4': '.mp4',
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/webm': '.webm',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
    'audio/aac': '.aac',
    'audio/amr': '.amr',
}


def is_audio_message(message: dict) -> bool:
    """Verifica se a mensagem é um áudio/PTT enviado pelo usuário."""
    msg_type = (message.get('type') or '').lower()
    return msg_type in SUPPORTED_AUDIO_TYPES


def transcribe_audio_message(message: dict, wpp_service=None, session_name: str = None):
    """
    Extrai o áudio do payload WPP Connect e transcreve usando OpenAI Whisper.
    Retorna o texto transcrito ou None em caso de falha.
    Tenta múltiplas estratégias para obter os bytes do áudio:
      1. body como data URI base64  (data:audio/...;base64,...)
      2. body como base64 puro
      3. mediaUrl ou body como URL HTTP(S)
      4. Download via API do WPP Connect usando o messageId
    """
    audio_data = None
    mimetype = _clean_mime(message.get('mimetype', 'audio/ogg'))
    body = message.get('body', '') or ''

    # Estratégia 1: data URI (data:audio/ogg;base64,XXXXX)
    if body.startswith('data:'):
        try:
            header, b64data = body.split(',', 1)
            audio_data = base64.b64decode(b64data)
            mime_part = header.split(';')[0].replace('data:', '').strip()
            if mime_part:
                mimetype = _clean_mime(mime_part)
            print(f"[Audio] Áudio obtido via data URI. Tamanho: {len(audio_data)} bytes")
        except Exception as e:
            print(f"[Audio] Erro ao decodificar data URI: {e}")

    # Estratégia 2: base64 puro (sem prefixo data:)
    if not audio_data and body and not body.startswith('http') and len(body) > 100:
        try:
            decoded = base64.b64decode(body + '==')
            if len(decoded) > 500:
                audio_data = decoded
                print(f"[Audio] Áudio obtido via base64 puro. Tamanho: {len(audio_data)} bytes")
        except Exception:
            pass

    # Estratégia 3: URL (mediaUrl ou body começando com http)
    if not audio_data:
        media_url = message.get('mediaUrl') or (body if body.startswith('http') else None)
        if media_url:
            try:
                resp = requests.get(media_url, timeout=30)
                if resp.status_code == 200:
                    audio_data = resp.content
                    ct = resp.headers.get('Content-Type', '')
                    if ct:
                        mimetype = _clean_mime(ct)
                    print(f"[Audio] Áudio baixado da URL. Tamanho: {len(audio_data)} bytes")
                else:
                    print(f"[Audio] Falha ao baixar URL {media_url}: HTTP {resp.status_code}")
            except Exception as e:
                print(f"[Audio] Erro ao baixar da URL: {e}")

    # Estratégia 4: API do WPP Connect (download-media via messageId)
    if not audio_data and wpp_service:
        message_id = message.get('id') or message.get('msgId')
        if message_id:
            print(f"[Audio] Tentando download via WPP Connect API: {message_id}")
            audio_data, mime_from_api = wpp_service.download_media(message_id, session_name)
            if mime_from_api:
                mimetype = _clean_mime(mime_from_api)
            if audio_data:
                print(f"[Audio] Áudio obtido via WPP API. Tamanho: {len(audio_data)} bytes")

    if not audio_data:
        print("[Audio] Não foi possível obter os dados do áudio por nenhuma estratégia.")
        return None

    ext = AUDIO_MIME_TO_EXT.get(mimetype, '.ogg')
    return _transcribe_with_whisper(audio_data, ext)


def _clean_mime(mimetype: str) -> str:
    """Retorna apenas a parte principal do MIME type (sem parâmetros adicionais)."""
    if not mimetype:
        return 'audio/ogg'
    clean = mimetype.split(';')[0].strip().lower()
    if 'ogg' in clean:
        return 'audio/ogg'
    return clean


def _transcribe_with_whisper(audio_data: bytes, ext: str = '.ogg'):
    """Envia o áudio para o OpenAI Whisper e retorna a transcrição em texto."""
    try:
        from app.models.ai_model import _get_openai_client
        client = _get_openai_client()

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        try:
            with open(tmp_path, 'rb') as audio_file:
                response = client.audio.transcriptions.create(
                    model='whisper-1',
                    file=audio_file,
                    language='pt',
                    response_format='text'
                )
            transcription = (response or '').strip()
            print(f"[Audio] Transcrição Whisper: '{transcription[:120]}'")
            return transcription if transcription else None
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        print(f"[Audio] Erro ao transcrever com Whisper: {e}")
        import traceback
        traceback.print_exc()
        return None
