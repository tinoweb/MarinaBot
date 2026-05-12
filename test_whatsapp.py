"""
Script de teste para validar a conexao com o WhatsApp via WPP-Whatsapp.

Este script inicia o bot, aguarda a autenticacao por QR code e responde
mensagens com uma saudacao simples (sem IA, apenas para testar a conexao).

Como usar:
    python test_whatsapp.py

Requisitos:
    - Dependencias instaladas: pip install -r requirements.txt
    - Playwright instalado: playwright install chromium
"""

import time
from WPP_Whatsapp import Create


def on_message(message):
    """Handler simples para testar recebimento e envio de mensagens."""
    if message.get("isGroupMsg"):
        return

    sender_id = message.get("from", "")
    text = message.get("body", "").strip()

    print(f"[TESTE] Recebido de {sender_id}: {text}")

    try:
        client.sendText(sender_id, f"Ola! Voce enviou: '{text}'. Conexao OK! ✅")
        print(f"[TESTE] Resposta enviada para {sender_id}")
    except Exception as e:
        print(f"[TESTE] Erro ao enviar resposta: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("TESTE DE CONEXAO - WhatsApp Bot (WPP-Whatsapp)")
    print("=" * 60)
    print("Iniciando sessao... Escaneie o QR code quando solicitado.")
    print("Pressione Ctrl+C para encerrar.")
    print("=" * 60)

    try:
        creator = Create(session="teste_conexao")
        global client
        client = creator.start()

        client.on_message(on_message)
        client.start()

    except KeyboardInterrupt:
        print("\n[Teste] Encerrado pelo usuario.")
    except Exception as e:
        print(f"\n[Teste] Erro: {e}")
