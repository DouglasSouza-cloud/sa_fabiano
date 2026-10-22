-- ============================================================
-- HEIMDALL - Sistema de controle de tablets
-- Schema MySQL 8.0.16+ (usa CHECK e coluna gerada)
-- ============================================================


-- ============================================================
-- 1. USUÁRIOS ADMINISTRADORES
-- ============================================================
CREATE TABLE usuarios_admin (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    usuario VARCHAR(60) NOT NULL UNIQUE,
    senha_hash VARCHAR(255) NOT NULL,
    perfil ENUM('admin', 'operador') NOT NULL DEFAULT 'operador',
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    tentativas_falhas INT NOT NULL DEFAULT 0,
    bloqueado_ate DATETIME NULL,
    ultimo_login_em DATETIME NULL,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;


-- ============================================================
-- 2. DISPOSITIVOS ESP32
-- ============================================================


CREATE TABLE dispositivos (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    identificador VARCHAR(60) NOT NULL UNIQUE,
    nome VARCHAR(120) NOT NULL,
    chave_hash VARCHAR(64) NOT NULL UNIQUE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    simulado BOOLEAN NOT NULL DEFAULT FALSE,
    ultimo_contato_em DATETIME NULL,
    ultimo_ip VARCHAR(45) NULL,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;


-- ============================================================
-- 3. PROFESSORES
-- ============================================================


CREATE TABLE professores (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    matricula VARCHAR(40) NOT NULL UNIQUE,
    uid_cracha VARCHAR(32) NOT NULL UNIQUE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;


-- ============================================================
-- 4. TABLETS
-- ============================================================
-- O status 'reservado' foi mantido no ENUM, mas nao e mais usado:
-- a reserva e por quantidade (tabela reservas), nao por tablet.


CREATE TABLE tablets (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    patrimonio VARCHAR(40) NOT NULL UNIQUE,
    epc VARCHAR(48) NOT NULL UNIQUE,
    marca VARCHAR(60) NULL,
    modelo VARCHAR(80) NULL,
    numero_serie VARCHAR(80) NULL,
    status ENUM(
        'disponivel',
        'emprestado',
        'manutencao',
        'indisponivel',
        'reservado'
    ) NOT NULL DEFAULT 'disponivel',
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;


-- ============================================================
-- 5. REGISTROS DE INVENTÁRIO
-- ============================================================


CREATE TABLE inventario_snapshots (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    dispositivo_id INT UNSIGNED NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    inventario_id VARCHAR(64) NULL,
    origem ENUM('real', 'simulacao') NOT NULL DEFAULT 'real',
    completo BOOLEAN NOT NULL DEFAULT FALSE,
    qualidade DECIMAL(4,3) NULL,
    valido BOOLEAN NOT NULL DEFAULT FALSE,
    motivo_invalido VARCHAR(255) NULL,
    confirmado BOOLEAN NOT NULL DEFAULT FALSE,
    referencia BOOLEAN NOT NULL DEFAULT FALSE,
    total_epcs INT UNSIGNED NOT NULL DEFAULT 0,
    epcs JSON NOT NULL,
    epcs_desconhecidos JSON NULL,
    num_leituras INT UNSIGNED NOT NULL DEFAULT 0,
    lido_em DATETIME NULL,
    recebido_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,


    CONSTRAINT uq_snapshot_request
        UNIQUE (dispositivo_id, request_id),


    CONSTRAINT fk_snapshot_dispositivo
        FOREIGN KEY (dispositivo_id)
        REFERENCES dispositivos(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT chk_snapshot_qualidade
        CHECK (qualidade IS NULL OR qualidade BETWEEN 0 AND 1),


    INDEX idx_snapshot_inventario (inventario_id),
    INDEX idx_snapshot_recebido (recebido_em),
    INDEX idx_snapshot_referencia (referencia, confirmado)
) ENGINE=InnoDB;


-- ============================================================
-- 6. RESERVAS (por quantidade, sem tablet especifico)
-- ============================================================
-- Regras aplicadas pelo backend:
--   * antecedencia maxima de 24h;
--   * tolerancia de 30 min apos o inicio (depois vira 'expirada');
--   * soma das reservas sobrepostas nao pode passar do total de
--     tablets do armario.


CREATE TABLE reservas (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    professor_id INT UNSIGNED NOT NULL,
    dispositivo_id INT UNSIGNED NOT NULL,
    quantidade SMALLINT UNSIGNED NOT NULL,
    inicio_em DATETIME NOT NULL,
    fim_em DATETIME NOT NULL,
    status ENUM(
        'ativa',
        'em_uso',
        'concluida',
        'cancelada',
        'expirada'
    ) NOT NULL DEFAULT 'ativa',
    observacao TEXT NULL,
    criada_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizada_em DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,


    CONSTRAINT fk_reserva_professor
        FOREIGN KEY (professor_id)
        REFERENCES professores(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT fk_reserva_dispositivo
        FOREIGN KEY (dispositivo_id)
        REFERENCES dispositivos(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT chk_reserva_quantidade
        CHECK (quantidade > 0),


    CONSTRAINT chk_reserva_periodo
        CHECK (fim_em > inicio_em),


    INDEX idx_reserva_periodo (dispositivo_id, inicio_em, fim_em),
    INDEX idx_reserva_professor (professor_id),
    INDEX idx_reserva_status (status)
) ENGINE=InnoDB;


-- ============================================================
-- 7. EMPRÉSTIMOS
-- ============================================================


CREATE TABLE emprestimos (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    professor_id INT UNSIGNED NOT NULL,
    dispositivo_id INT UNSIGNED NOT NULL,
    reserva_id BIGINT UNSIGNED NULL,
    request_id VARCHAR(64) NOT NULL,
    origem ENUM('real', 'simulacao') NOT NULL DEFAULT 'real',
    status ENUM(
        'aberta',
        'aguardando_confirmacao',
        'fechada',
        'expirada',
        'ocorrencia'
    ) NOT NULL DEFAULT 'aberta',
    aberta_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fechada_em DATETIME NULL,
    snapshot_inicial_id BIGINT UNSIGNED NULL,
    observacao TEXT NULL,


    CONSTRAINT uq_emprestimo_request
        UNIQUE (dispositivo_id, request_id),


    CONSTRAINT fk_emprestimo_professor
        FOREIGN KEY (professor_id)
        REFERENCES professores(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT fk_emprestimo_dispositivo
        FOREIGN KEY (dispositivo_id)
        REFERENCES dispositivos(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT fk_emprestimo_reserva
        FOREIGN KEY (reserva_id)
        REFERENCES reservas(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_emprestimo_snapshot_inicial
        FOREIGN KEY (snapshot_inicial_id)
        REFERENCES inventario_snapshots(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT chk_emprestimo_datas
        CHECK (fechada_em IS NULL OR fechada_em >= aberta_em),


    INDEX idx_emprestimo_professor (professor_id),
    INDEX idx_emprestimo_reserva (reserva_id),
    INDEX idx_emprestimo_status (status),
    INDEX idx_emprestimo_abertura (aberta_em)
) ENGINE=InnoDB;


-- ============================================================
-- 8. ITENS DE CADA EMPRÉSTIMO
-- ============================================================


CREATE TABLE emprestimo_itens (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    emprestimo_id BIGINT UNSIGNED NOT NULL,
    tablet_id INT UNSIGNED NOT NULL,
    retirado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    devolvido_em DATETIME NULL,
    snapshot_retirada_id BIGINT UNSIGNED NULL,
    snapshot_devolucao_id BIGINT UNSIGNED NULL,
    devolvido_por_professor_id INT UNSIGNED NULL,
    aberto_flag TINYINT
        GENERATED ALWAYS AS (
            IF(devolvido_em IS NULL, 1, NULL)
        ) STORED,


    CONSTRAINT uq_tablet_emprestimo_aberto
        UNIQUE (tablet_id, aberto_flag),


    CONSTRAINT fk_item_emprestimo
        FOREIGN KEY (emprestimo_id)
        REFERENCES emprestimos(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT fk_item_tablet
        FOREIGN KEY (tablet_id)
        REFERENCES tablets(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT fk_item_snapshot_retirada
        FOREIGN KEY (snapshot_retirada_id)
        REFERENCES inventario_snapshots(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_item_snapshot_devolucao
        FOREIGN KEY (snapshot_devolucao_id)
        REFERENCES inventario_snapshots(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_item_professor_devolucao
        FOREIGN KEY (devolvido_por_professor_id)
        REFERENCES professores(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT chk_item_datas
        CHECK (
            devolvido_em IS NULL
            OR devolvido_em >= retirado_em
        ),


    INDEX idx_item_emprestimo (emprestimo_id),
    INDEX idx_item_tablet (tablet_id)
) ENGINE=InnoDB;


-- ============================================================
-- 9. LOG DE LEITURAS E EVENTOS
-- ============================================================


CREATE TABLE leituras_log (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    dispositivo_id INT UNSIGNED NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    tipo_evento ENUM(
        'cracha',
        'inventario',
        'porta',
        'falha_comunicacao',
        'erro_leitor',
        'heartbeat'
    ) NOT NULL,
    origem ENUM('real', 'simulacao') NOT NULL DEFAULT 'real',
    uid_cracha VARCHAR(32) NULL,
    epc VARCHAR(48) NULL,
    leitura_id VARCHAR(64) NULL,
    completa BOOLEAN NULL,
    lido_em DATETIME NULL,
    recebido_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resultado ENUM(
        'pendente',
        'processado',
        'ignorado',
        'rejeitado',
        'erro'
    ) NOT NULL DEFAULT 'pendente',
    detalhe TEXT NULL,
    http_status SMALLINT UNSIGNED NULL,
    payload_json JSON NULL,
    resposta_json JSON NULL,
    emprestimo_id BIGINT UNSIGNED NULL,
    snapshot_id BIGINT UNSIGNED NULL,


    CONSTRAINT uq_leitura_request
        UNIQUE (dispositivo_id, request_id),


    CONSTRAINT fk_leitura_dispositivo
        FOREIGN KEY (dispositivo_id)
        REFERENCES dispositivos(id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,


    CONSTRAINT fk_leitura_emprestimo
        FOREIGN KEY (emprestimo_id)
        REFERENCES emprestimos(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_leitura_snapshot
        FOREIGN KEY (snapshot_id)
        REFERENCES inventario_snapshots(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    INDEX idx_leitura_tipo (tipo_evento),
    INDEX idx_leitura_resultado (resultado),
    INDEX idx_leitura_recebido (recebido_em),
    INDEX idx_leitura_uid (uid_cracha),
    INDEX idx_leitura_epc (epc)
) ENGINE=InnoDB;


-- ============================================================
-- 10. OCORRÊNCIAS
-- ============================================================


CREATE TABLE ocorrencias (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tipo ENUM(
        'retirada_sem_sessao',
        'sessoes_concorrentes',
        'epc_desconhecido',
        'devolucao_outro_professor',
        'leitura_incompleta_repetida',
        'tablet_indisponivel_retirado',
        'retirada_acima_do_limite',
        'outro'
    ) NOT NULL,
    status ENUM(
        'aberta',
        'resolvida',
        'descartada'
    ) NOT NULL DEFAULT 'aberta',
    origem ENUM('real', 'simulacao') NOT NULL DEFAULT 'real',
    dispositivo_id INT UNSIGNED NULL,
    emprestimo_id BIGINT UNSIGNED NULL,
    tablet_id INT UNSIGNED NULL,
    snapshot_id BIGINT UNSIGNED NULL,
    descricao TEXT NOT NULL,
    criada_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolvida_em DATETIME NULL,
    resolvida_por INT UNSIGNED NULL,
    resolucao TEXT NULL,


    CONSTRAINT fk_ocorrencia_dispositivo
        FOREIGN KEY (dispositivo_id)
        REFERENCES dispositivos(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_ocorrencia_emprestimo
        FOREIGN KEY (emprestimo_id)
        REFERENCES emprestimos(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_ocorrencia_tablet
        FOREIGN KEY (tablet_id)
        REFERENCES tablets(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_ocorrencia_snapshot
        FOREIGN KEY (snapshot_id)
        REFERENCES inventario_snapshots(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    CONSTRAINT fk_ocorrencia_usuario
        FOREIGN KEY (resolvida_por)
        REFERENCES usuarios_admin(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    INDEX idx_ocorrencia_status (status),
    INDEX idx_ocorrencia_tipo (tipo),
    INDEX idx_ocorrencia_criada (criada_em)
) ENGINE=InnoDB;


-- ============================================================
-- 11. AUDITORIA DE AÇÕES ADMINISTRATIVAS
-- ============================================================


CREATE TABLE auditoria (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT UNSIGNED NULL,
    acao VARCHAR(100) NOT NULL,
    entidade VARCHAR(100) NULL,
    entidade_id VARCHAR(64) NULL,
    detalhes JSON NULL,
    ip VARCHAR(45) NULL,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,


    CONSTRAINT fk_auditoria_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES usuarios_admin(id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,


    INDEX idx_auditoria_usuario (usuario_id),
    INDEX idx_auditoria_acao (acao),
    INDEX idx_auditoria_criado (criado_em),
    INDEX idx_auditoria_entidade (entidade, entidade_id)
) ENGINE=InnoDB;


-- ============================================================
-- VIEWS
-- ============================================================


-- Tablets atualmente emprestados
CREATE VIEW vw_tablets_emprestados AS
SELECT
    t.id AS tablet_id,
    t.patrimonio,
    t.epc,
    t.marca,
    t.modelo,
    p.id AS professor_id,
    p.nome AS professor,
    p.matricula,
    e.id AS emprestimo_id,
    e.reserva_id,
    e.aberta_em AS data_retirada,
    ei.retirado_em
FROM emprestimo_itens ei
INNER JOIN tablets t
    ON t.id = ei.tablet_id
INNER JOIN emprestimos e
    ON e.id = ei.emprestimo_id
INNER JOIN professores p
    ON p.id = e.professor_id
WHERE ei.devolvido_em IS NULL;


-- Histórico de empréstimos por professor
CREATE VIEW vw_historico_professor AS
SELECT
    p.id AS professor_id,
    p.nome AS professor,
    p.matricula,
    e.id AS emprestimo_id,
    e.reserva_id,
    e.status AS status_emprestimo,
    e.aberta_em,
    e.fechada_em,
    t.id AS tablet_id,
    t.patrimonio,
    t.epc,
    ei.retirado_em,
    ei.devolvido_em
FROM professores p
INNER JOIN emprestimos e
    ON e.professor_id = p.id
INNER JOIN emprestimo_itens ei
    ON ei.emprestimo_id = e.id
INNER JOIN tablets t
    ON t.id = ei.tablet_id;


-- Reservas que ainda seguram tablets (ativas ou em uso)
CREATE VIEW vw_reservas_vigentes AS
SELECT
    r.id AS reserva_id,
    r.dispositivo_id,
    r.quantidade,
    r.inicio_em,
    r.fim_em,
    r.status,
    p.id AS professor_id,
    p.nome AS professor,
    p.matricula
FROM reservas r
INNER JOIN professores p
    ON p.id = r.professor_id
WHERE r.status IN ('ativa', 'em_uso');


-- ============================================================
-- FIM DO SCRIPT
-- ============================================================
