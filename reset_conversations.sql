-- Limpa apenas conversas e dados de clientes
-- MANTÉM: sessão WhatsApp, configurações, IA settings
-- EXECUTAR NO SERVIDOR DE PRODUÇÃO COM CUIDADO

USE marina_bot;

-- Limpa mensagens das conversas
DELETE FROM chat_messages;

-- Limpa dados de usuário coletados
DELETE FROM user_data;

-- Limpa sessões de chat
DELETE FROM chat_sessions;

-- Reseta auto-increment das tabelas (opcional)
ALTER TABLE chat_sessions AUTO_INCREMENT = 1;
ALTER TABLE chat_messages AUTO_INCREMENT = 1;
ALTER TABLE user_data AUTO_INCREMENT = 1;

SELECT 'Conversas e dados de clientes limpos com sucesso' AS status;
