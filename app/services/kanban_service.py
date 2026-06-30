"""
Serviço de Kanban/Mini-CRM para classificação automática de leads por benefício.
Stages:
  atendimento_inicial → [benefício detectado] → falta_documentos / fechou_contrato / lead_desqualificado
Regras de valor:
  - Salário Maternidade (urbano/rural) e Auxílio Doença: podem discutir valores.
  - Demais benefícios: encaminhar para agendamento apenas.
"""

import unicodedata
import re
from app.config.database import get_db_connection

# ── Definição dos estágios ────────────────────────────────────────────────────

STAGES = [
    {
        'key': 'atendimento_inicial',
        'name': 'Atendimento Inicial',
        'type': 'initial',
        'color': '#4a90e2',
        'icon': 'fa-headset',
        'can_discuss_value': False,
        'requires_scheduling': False,
        'keywords': [],
        'position': 0,
    },
    {
        'key': 'salario_maternidade_urbano',
        'name': 'Salário Maternidade Urbano',
        'type': 'benefit',
        'color': '#e2914a',
        'icon': 'fa-baby',
        'can_discuss_value': True,
        'requires_scheduling': False,
        'keywords': [
            'salario maternidade urbano', 'maternidade urbano',
            'salario maternidade', 'salario-maternidade',
            'maternidade', 'gestante', 'gravida', 'grav ida',
            'licenca maternidade', 'licença maternidade',
            'parto', 'nascimento', 'bebe', 'bebe nasceu',
            'empregada', 'carteira assinada', 'clt',
        ],
        'position': 1,
    },
    {
        'key': 'salario_maternidade_rural',
        'name': 'Salário Maternidade Rural',
        'type': 'benefit',
        'color': '#4caf50',
        'icon': 'fa-seedling',
        'can_discuss_value': True,
        'requires_scheduling': True,
        'keywords': [
            'maternidade rural', 'salario maternidade rural',
            'rural', 'roca', 'agricultura', 'agricultora',
            'trabalhadora rural', 'lavrador', 'lavradora',
            'segurada especial', 'campo', 'sitio', 'fazenda',
            'producao rural', 'pequeno produtor',
        ],
        'position': 2,
    },
    {
        'key': 'auxilio_doenca',
        'name': 'Auxílio Doença',
        'type': 'benefit',
        'color': '#e53935',
        'icon': 'fa-heart-pulse',
        'can_discuss_value': True,
        'requires_scheduling': False,
        'keywords': [
            'auxilio doenca', 'auxilio-doenca', 'beneficio doenca',
            'afastamento', 'incapacidade', 'incapaz', 'doente',
            'doenca', 'cirurgia', 'operacao', 'hospital',
            'internacao', 'tratamento medico', 'lesao', 'fratura',
            'nao consigo trabalhar', 'parar de trabalhar',
            'medico mandou afastar',
        ],
        'position': 3,
    },
    {
        'key': 'aposentadoria',
        'name': 'Aposentadoria',
        'type': 'benefit',
        'color': '#7b1fa2',
        'icon': 'fa-person-cane',
        'can_discuss_value': False,
        'requires_scheduling': True,
        'keywords': [
            'aposentadoria', 'aposentar', 'aposentado', 'aposentada',
            'tempo de contribuicao', 'anos trabalhados',
            'contribuicao', 'me aposentar', 'quero me aposentar',
        ],
        'position': 4,
    },
    {
        'key': 'pensao_por_morte',
        'name': 'Pensão por Morte',
        'type': 'benefit',
        'color': '#37474f',
        'icon': 'fa-cross',
        'can_discuss_value': False,
        'requires_scheduling': True,
        'keywords': [
            'pensao por morte', 'pensao-por-morte',
            'pensao', 'faleceu', 'falecimento', 'morreu', 'obito',
            'morte', 'viuvo', 'viuva', 'conjuge faleceu',
            'marido morreu', 'esposa morreu', 'pai morreu',
            'mae morreu', 'dependente', 'inventario',
        ],
        'position': 5,
    },
    {
        'key': 'bpc_loas_idoso',
        'name': 'BPC LOAS Idoso',
        'type': 'benefit',
        'color': '#f57c00',
        'icon': 'fa-user-clock',
        'can_discuss_value': False,
        'requires_scheduling': True,
        'keywords': [
            'bpc idoso', 'loas idoso', 'beneficio assistencial idoso',
            'nao contribuiu', 'nunca contribuiu', 'nunca trabalhou com carteira',
            'idoso sem beneficio', '65 anos sem', 'beneficio sem contribuicao',
        ],
        'position': 6,
    },
    {
        'key': 'bpc_loas_deficiente',
        'name': 'BPC LOAS Deficiente',
        'type': 'benefit',
        'color': '#ef6c00',
        'icon': 'fa-wheelchair',
        'can_discuss_value': False,
        'requires_scheduling': True,
        'keywords': [
            'bpc deficiente', 'loas deficiente', 'bpc pcd',
            'deficiente', 'deficiencia', 'pcd', 'pessoa com deficiencia',
            'laudo medico', 'laudo', 'autismo', 'cadeirante',
            'incapacitado permanente', 'bpc', 'loas',
            'assistencial', 'beneficio assistencial',
        ],
        'position': 7,
    },
    {
        'key': 'auxilio_acidente',
        'name': 'Auxílio Acidente',
        'type': 'benefit',
        'color': '#c62828',
        'icon': 'fa-triangle-exclamation',
        'can_discuss_value': False,
        'requires_scheduling': True,
        'keywords': [
            'auxilio acidente', 'acidente de trabalho',
            'acidente trabalho', 'sequela', 'acidente',
            'lesao permanente', 'acidentei', 'me acidentei',
        ],
        'position': 8,
    },
    {
        'key': 'auxilio_reclusao',
        'name': 'Auxílio Reclusão',
        'type': 'benefit',
        'color': '#263238',
        'icon': 'fa-lock',
        'can_discuss_value': False,
        'requires_scheduling': True,
        'keywords': [
            'auxilio reclusao', 'reclusao', 'preso', 'detento',
            'presidio', 'cadeia', 'familia preso', 'marido preso',
            'esposo preso', 'pai preso', 'filho preso',
            'preso preventivo', 'cumprindo pena',
        ],
        'position': 9,
    },
    {
        'key': 'falta_documentos',
        'name': 'Falta Enviar Documentos',
        'type': 'document',
        'color': '#f9a825',
        'icon': 'fa-file-circle-exclamation',
        'can_discuss_value': False,
        'requires_scheduling': False,
        'keywords': [],
        'position': 10,
    },
    {
        'key': 'fechou_contrato',
        'name': 'Fechou Contrato',
        'type': 'closed',
        'color': '#2e7d32',
        'icon': 'fa-handshake',
        'can_discuss_value': False,
        'requires_scheduling': False,
        'keywords': [],
        'position': 11,
    },
    {
        'key': 'lead_desqualificado',
        'name': 'Lead Desqualificado',
        'type': 'disqualified',
        'color': '#616161',
        'icon': 'fa-user-xmark',
        'can_discuss_value': False,
        'requires_scheduling': False,
        'keywords': [],
        'position': 12,
    },
]

STAGES_BY_KEY = {s['key']: s for s in STAGES}

# Mapeia qualificacao existente → kanban_stage
_QUALIFICACAO_TO_STAGE = {
    'descarte_1': 'lead_desqualificado',
    'descarte_2': 'lead_desqualificado',
    'fechamento': 'fechou_contrato',
    'pos_venda': 'fechou_contrato',
    'aguardando_docs': 'falta_documentos',
    'docs_recebidos': 'falta_documentos',
}

# Estágios "finais" - não devem ser sobrescritos por classificação de keywords
_FINAL_STAGES = {'falta_documentos', 'fechou_contrato', 'lead_desqualificado'}

# Benefit stages que permitem reclassificação por keywords
_BENEFIT_STAGES = {s['key'] for s in STAGES if s['type'] == 'benefit'}


# ── Normalização de texto ────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Remove acentos, pontuação e normaliza para lowercase."""
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Classificação por keywords ───────────────────────────────────────────────

def classify_by_keywords(text: str):
    """
    Recebe o texto do usuário e retorna a stage_key do benefício identificado,
    ou None se não houver match.
    Prioridade: keywords mais longas (mais específicas) ganham.
    """
    norm = _normalize(text)

    best_key = None
    best_len = 0

    for stage in STAGES:
        if stage['type'] != 'benefit':
            continue
        for kw in stage['keywords']:
            kw_norm = _normalize(kw)
            if kw_norm in norm and len(kw_norm) > best_len:
                best_len = len(kw_norm)
                best_key = stage['key']

    return best_key


# ── Persistência no banco ────────────────────────────────────────────────────

def get_session_kanban_stage(session_id: int) -> str:
    """Retorna o kanban_stage atual da sessão (default: atendimento_inicial)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT kanban_stage FROM chat_sessions WHERE id=%s LIMIT 1",
            (session_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return (row or {}).get('kanban_stage') or 'atendimento_inicial'
    except Exception as e:
        print(f"[Kanban] Erro ao ler kanban_stage: {e}")
        return 'atendimento_inicial'


def move_session_to_stage(session_id: int, stage_key: str) -> bool:
    """Atualiza o kanban_stage da sessão no banco."""
    if stage_key not in STAGES_BY_KEY:
        print(f"[Kanban] Stage desconhecida: {stage_key}")
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET kanban_stage=%s WHERE id=%s",
            (stage_key, session_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[Kanban] Sessão {session_id} → {stage_key}")
        return True
    except Exception as e:
        print(f"[Kanban] Erro ao mover sessão: {e}")
        return False


# ── Classificação automática ─────────────────────────────────────────────────

def auto_classify_session(session_id: int, new_text: str, qualificacao: str = None) -> str:
    """
    Tenta classificar/mover automaticamente o lead no kanban.
    Retorna a stage_key final após avaliação.
    Prioridade:
      1. qualificacao (descarte/fechamento/docs) → stage final
      2. keywords no texto (apenas se ainda em initial ou benefit não-final)
    """
    current_stage = get_session_kanban_stage(session_id)

    # Prioridade 1: qualificacao override
    if qualificacao and qualificacao in _QUALIFICACAO_TO_STAGE:
        target = _QUALIFICACAO_TO_STAGE[qualificacao]
        if current_stage != target:
            move_session_to_stage(session_id, target)
            return target
        return current_stage

    # Prioridade 2: keywords (apenas se não estiver em stage final)
    if current_stage not in _FINAL_STAGES:
        classified = classify_by_keywords(new_text)
        if classified and classified != current_stage:
            # Não reclassificar se já está em um benefício diferente
            # (evita troca por menção casual a outro benefício)
            if current_stage == 'atendimento_inicial' or current_stage in _BENEFIT_STAGES:
                move_session_to_stage(session_id, classified)
                return classified

    return current_stage


# ── Dados do board ───────────────────────────────────────────────────────────

def get_board_data() -> dict:
    """
    Retorna todos os leads agrupados por kanban_stage para o board.
    Cada card inclui: id, user_id, nome, ultimo_contato, last_message,
    qualificacao, etapa_atual, kanban_stage.
    """
    result = {s['key']: [] for s in STAGES}

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                cs.id,
                cs.user_id,
                cs.updated_at,
                cs.last_message,
                cs.qualificacao,
                cs.etapa_atual,
                cs.ia_pausada,
                COALESCE(cs.kanban_stage, 'atendimento_inicial') AS kanban_stage,
                MAX(CASE WHEN ud.key_name IN ('nome_completo','nome','nome_wpp')
                         THEN ud.value END) AS nome,
                MAX(CASE WHEN ud.key_name = 'real_phone'
                         THEN ud.value END) AS telefone
            FROM chat_sessions cs
            LEFT JOIN user_data ud ON ud.session_id = cs.id
            WHERE cs.status != 'archived'
            GROUP BY cs.id
            ORDER BY cs.updated_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        for row in rows:
            stage_key = row.get('kanban_stage') or 'atendimento_inicial'
            if stage_key not in result:
                stage_key = 'atendimento_inicial'
            # Formata
            updated = row.get('updated_at')
            row['updated_at_str'] = updated.strftime('%d/%m %H:%M') if updated else ''
            last_msg = (row.get('last_message') or '')
            row['last_message_short'] = last_msg[:60] + '...' if len(last_msg) > 60 else last_msg
            row['stage_info'] = STAGES_BY_KEY.get(stage_key, STAGES[0])
            result[stage_key].append(row)

    except Exception as e:
        print(f"[Kanban] Erro ao carregar board: {e}")

    return result


def get_stage_counts() -> dict:
    """Retorna contagem de leads por stage."""
    counts = {s['key']: 0 for s in STAGES}
    data = get_board_data()
    for key, cards in data.items():
        counts[key] = len(cards)
    return counts
