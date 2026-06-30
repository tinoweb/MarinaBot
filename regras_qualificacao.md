# Regras de Qualificação do Sistema - Camila (Marques Advogados)

Este documento reúne de forma organizada todas as regras de triagem e qualificação de clientes utilizadas pela assistente virtual Camila.

---

## 1. Gestante
* **Faltam mais de 30 dias para o parto:** 
  * Status: **Qualificada** (`qualificada`)
  * Ação: Prossiga com o fluxo para qualificar a situação de trabalho. Se urbana, avance para coleta de documentos (Etapa 8).
* **Faltam 30 dias ou menos:** 
  * Status: **Qualificada** (`qualificada`)
  * Ação: Informe urgência no atendimento e prossiga com o fluxo.

## 2. Bebê já Nasceu
* **Ainda no mesmo mês do parto:** 
  * Status: **Qualificada** (`qualificada`)
  * Ação: Prossiga para a situação de trabalho.
* **Até o dia 15 do mês seguinte ao parto:** 
  * Status: **Qualificada** (`qualificada`)
  * Ação: Prossiga para a situação de trabalho.
* **Após o dia 15 do mês seguinte ao nascimento:** 
  * Status: **Não Qualificada** (`descarte_2`)
  * Ação: Ofereça a possibilidade de encaminhamento para análise excepcional da Dra. Marina Marques.

## 3. Cliente CLT
* **Trabalhando atualmente:**
  * **Trabalha há 1 mês ou mais:** 
    * Status: **Qualificada** (`qualificada`)
  * **Trabalha há menos de 1 mês:** 
    * Status: **Pendente** (`pendente`)
    * Ação: Encaminhar para atendimento humano.
* **Desempregada:**
  * **Até 1 ano desempregada:** 
    * Status: **Qualificada** (`qualificada`)
  * **Mais de 1 ano desempregada:** 
    * Pergunta: *Recebeu seguro-desemprego?*
      * **Sim:** Status: **Qualificada** (`qualificada`)
      * **Não:** Pergunta: *Enviou currículos por e-mail ou WhatsApp?*
        * **Sim:** Status: **Qualificada** (`qualificada`)
        * **Não:** Status: **Pendente** (`pendente`) &rarr; Encaminhar para atendimento humano.

## 4. CLT + Renda Extra
* **Regra:** Após a qualificação CLT, pergunta-se se a cliente possui outra fonte de renda (venda de produtos, manicure, cabeleireira, bolos, diarista, costureira, etc.).
* **Resultado:** Se **SIM**, a cliente recebe o perfil de **Salário Maternidade Duplo**.
* **Status:** **Qualificada** (`qualificada`)

## 5. Autônoma & 6. MEI
* **Está contribuindo atualmente?**
  * **Sim:** Status: **Qualificada** (`qualificada`)
  * **Não:** Pergunta: *Parou há quanto tempo?*
    * **Até 1 ano:** Status: **Qualificada** (`qualificada`)
    * **Mais de 1 ano:** Pergunta: *Recebeu seguro-desemprego ou enviou currículos recentemente?*
      * **Sim:** Status: **Qualificada** (`qualificada`)
      * **Não:** Status: **Pendente** (`pendente`) &rarr; Encaminhar para atendimento humano.

## 7. Trabalhadora Rural
* **Gestante:**
  * Pergunta: *Possui documentos rurais?* (DAP, CAF, Nota Fiscal, Sindicato, Declaração de produtor - no nome da cliente, pais, avós ou pessoas que moram junto).
    * **Tem documentos anteriores ao parto:** Status: **Qualificada** (`qualificada`) &rarr; Sendo rural, segue para o agendamento de consulta com a Dra. Marina Marques (NUNCA solicitar documentos pelo WhatsApp).
    * **Documentos posteriores ao parto:** Encaminhar para Caminho 5 (Sem carteira/sem documentos rurais).
    * **Não possui documentos:** Encaminhar para Caminho 5 (Sem carteira/sem documentos rurais).
* **Bebê já nasceu:**
  * Pergunta: *Possui documentos rurais anteriores ao nascimento?*
    * **Sim:** Status: **Qualificada** (`qualificada`) &rarr; Segue para o agendamento.
    * **Não:** Status: **Pendente** (`pendente`) &rarr; Encaminhar para atendimento humano.

## 8. Sem Carteira / Sem Documentos Rurais (Caminho 5)
* **Se passou do prazo do parto:** 
  * Status: **Não Qualificada** (`descarte_2`)
* **Se grávida:** Pergunta a idade.
  * **Urbana:**
    * **Menor de 16 anos:** Status: **Não Qualificada** (`descarte_1`) &rarr; Direciona para análise excepcional da Dra. Marina.
    * **16 anos ou mais:** Status: **Qualificada** (`qualificada`).
  * **Rural:**
    * **Qualquer idade:** Status: **Qualificada** (`qualificada`).

## 9. Cliente que já tentou o Benefício
* **Nunca tentou:** Segue o fluxo normal.
* **Tentou:** Pergunta se foi negado ou se está em análise.
  * **Sim (Foi negado):** Status: **Pendente** (`pendente`) &rarr; Encaminha diretamente para a Dra. Marina Marques.
  * **Ainda está em análise:** Status: **Pendente** (`pendente`) &rarr; Encaminha diretamente para a Dra. Marina Marques.

## 10. Clientes Descartados
* **Descarte 1 (Urbana menor de 16 anos):** É informada de que o planejamento padrão não se aplica, mas pode ser encaminhada para análise excepcional da Dra. Marina se desejar.
* **Descarte 2 (Passou do prazo / Óbito sem contribuição):** Informada de que o prazo passou, mas pode tentar análise excepcional da Dra. Marina se desejar.

## 11. Perfis Especiais
* **Perfil Duplo:** Cliente CLT qualificada + Renda Extra. É ofertada a possibilidade do Salário Maternidade Duplo.
* **Negativa do INSS / Processo em andamento:** Encaminhamento humano direto para a Dra. Marina Marques.

## 12. Pensão por Morte (Outros Benefícios)
* Pergunta: *A pessoa que faleceu contribuía para o INSS ou já era aposentada/recebia algum benefício na época do falecimento?*
  * **Sim:** Status: **Qualificada** (`qualificada`) &rarr; Oferece horários de agendamento de consulta. NUNCA solicitar documentos pelo WhatsApp.
  * **Não:** Status: **Não Qualificada** (`descarte_2`). Explique educadamente e encerre.

---

## Tabela Resumida de Marcação de Metadados (`[META]`)

A IA deve obrigatoriamente anexar na última linha da sua resposta o formato correspondente para que o sistema mova os leads no Kanban automaticamente:

| Cenário de Triagem | Tag de Metadados | Status no Kanban |
| :--- | :--- | :--- |
| **Em triagem (Pendente)** | `[META:etapa=2;qualif=pendente]` | Mantém na Etapa do Benefício |
| **Qualificada (Qualquer Benefício)** | `[META:etapa=3;qualif=qualificada]` | Mantém na Etapa do Benefício |
| **Aguardando Documentação (Urbano)** | `[META:etapa=8;qualif=aguardando_docs]` | Move para *Falta Enviar Documentos* |
| **Descarte 1 (Menor de 16 anos)** | `[META:etapa=3;qualif=descarte_1]` | Move para *Lead Desqualificado* |
| **Descarte 2 (Fora do prazo/regras)** | `[META:etapa=3;qualif=descarte_2]` | Move para *Lead Desqualificado* |
| **Encaminhamento Humano** | `[META:etapa=3;qualif=pendente]` | Mantém na Etapa do Benefício (IA pausa) |
