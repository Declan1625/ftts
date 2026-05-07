-- ============================================================
-- FTTS PostgreSQL Schema
-- Causal-Web Self-Diagnosing Stock Trading AI
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. sources (정보원 — S~D 등급)
-- ============================================================
CREATE TABLE sources (
    id                      SERIAL          PRIMARY KEY,
    name                    VARCHAR(200)    NOT NULL,
    url                     TEXT,
    type                    VARCHAR(50)     NOT NULL
                                CHECK (type IN ('blog', 'news', 'report', 'sns', 'official')),
    grade                   CHAR(1)         NOT NULL DEFAULT 'C'
                                CHECK (grade IN ('S', 'A', 'B', 'C', 'D')),
    grade_weight            NUMERIC(3,2)    NOT NULL DEFAULT 0.40,
    total_predictions       INTEGER         NOT NULL DEFAULT 0,
    correct_predictions     INTEGER         NOT NULL DEFAULT 0,
    accuracy                NUMERIC(5,4)    NOT NULL DEFAULT 0.0000,
    consecutive_d_count     INTEGER         NOT NULL DEFAULT 0,
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sources_grade  ON sources (grade);
CREATE INDEX idx_sources_active ON sources (is_active);
CREATE UNIQUE INDEX idx_sources_url ON sources (url) WHERE url IS NOT NULL;

-- ============================================================
-- 2. industries (산업)
-- ============================================================
CREATE TABLE industries (
    id          SERIAL          PRIMARY KEY,
    code        VARCHAR(20)     NOT NULL UNIQUE,
    name        VARCHAR(100)    NOT NULL,
    sector      VARCHAR(100),
    description TEXT,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_industries_sector ON industries (sector);

-- ============================================================
-- 3. companies (기업)
-- ============================================================
CREATE TABLE companies (
    id          SERIAL          PRIMARY KEY,
    ticker      VARCHAR(20)     NOT NULL UNIQUE,
    name        VARCHAR(200)    NOT NULL,
    market      VARCHAR(20)     NOT NULL
                    CHECK (market IN ('KOSPI', 'KOSDAQ', 'NYSE', 'NASDAQ', 'OTHER')),
    industry_id INTEGER         REFERENCES industries (id) ON DELETE SET NULL,
    description TEXT,
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_companies_industry ON companies (industry_id);
CREATE INDEX idx_companies_market   ON companies (market);
CREATE INDEX idx_companies_active   ON companies (is_active);

-- ============================================================
-- 4. stock_prices (주가 데이터)
-- ============================================================
CREATE TABLE stock_prices (
    id          BIGSERIAL       PRIMARY KEY,
    company_id  INTEGER         NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    price_date  DATE            NOT NULL,
    open        NUMERIC(14,2),
    high        NUMERIC(14,2),
    low         NUMERIC(14,2),
    close       NUMERIC(14,2)   NOT NULL,
    volume      BIGINT,
    adj_close   NUMERIC(14,2),
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, price_date)
);

CREATE INDEX idx_sp_company_date ON stock_prices (company_id, price_date DESC);
CREATE INDEX idx_sp_date         ON stock_prices (price_date DESC);

-- ============================================================
-- 5. events (수집된 사건)
-- ============================================================
CREATE TABLE events (
    id          SERIAL          PRIMARY KEY,
    title       VARCHAR(500)    NOT NULL,
    content     TEXT,
    source_id   INTEGER         NOT NULL REFERENCES sources (id) ON DELETE RESTRICT,
    industry_id INTEGER         REFERENCES industries (id) ON DELETE SET NULL,
    company_id  INTEGER         REFERENCES companies (id) ON DELETE SET NULL,
    event_type  VARCHAR(50)
                    CHECK (event_type IN (
                        'policy', 'earnings', 'macro', 'geopolitical',
                        'supply_chain', 'rate', 'commodity', 'other'
                    )),
    sentiment   NUMERIC(4,3)    CHECK (sentiment BETWEEN -1 AND 1),
    raw_score   NUMERIC(8,4),
    occurred_at TIMESTAMPTZ     NOT NULL,
    collected_at TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_source   ON events (source_id);
CREATE INDEX idx_events_industry ON events (industry_id);
CREATE INDEX idx_events_company  ON events (company_id);
CREATE INDEX idx_events_occurred ON events (occurred_at DESC);
CREATE INDEX idx_events_type     ON events (event_type);

-- ============================================================
-- 6. causal_edges (인과관계 지식 그래프)
-- ============================================================
CREATE TABLE causal_edges (
    id                  SERIAL          PRIMARY KEY,
    from_type           VARCHAR(20)     NOT NULL
                            CHECK (from_type IN ('event', 'industry', 'company')),
    from_id             INTEGER         NOT NULL,
    to_type             VARCHAR(20)     NOT NULL
                            CHECK (to_type IN ('event', 'industry', 'company')),
    to_id               INTEGER         NOT NULL,
    weight              NUMERIC(6,4)    NOT NULL DEFAULT 0.5000
                            CHECK (weight BETWEEN 0 AND 1),
    confidence          NUMERIC(5,4)    NOT NULL DEFAULT 0.5000
                            CHECK (confidence BETWEEN 0 AND 1),
    direction           SMALLINT        NOT NULL DEFAULT 1
                            CHECK (direction IN (1, -1)),
    observation_count   INTEGER         NOT NULL DEFAULT 1,
    last_triggered      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_causal_from   ON causal_edges (from_type, from_id);
CREATE INDEX idx_causal_to     ON causal_edges (to_type, to_id);
CREATE INDEX idx_causal_weight ON causal_edges (weight DESC);

-- ============================================================
-- 7. decisions (투자 결정 — 예측 시점 스냅샷)
-- ============================================================
CREATE TABLE decisions (
    id               SERIAL          PRIMARY KEY,
    company_id       INTEGER         NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    signal           VARCHAR(10)     NOT NULL CHECK (signal IN ('BUY', 'SELL', 'HOLD')),
    event_score      NUMERIC(10,4)   NOT NULL,
    predicted_weight NUMERIC(6,4)    NOT NULL,
    confidence       NUMERIC(5,4)    NOT NULL,
    logic_snapshot   JSONB,
    decided_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_decisions_company ON decisions (company_id);
CREATE INDEX idx_decisions_signal  ON decisions (signal);
CREATE INDEX idx_decisions_decided ON decisions (decided_at DESC);

-- ============================================================
-- 8. outcomes (실제 결과 — Self-Feedback 원천)
-- ============================================================
CREATE TABLE outcomes (
    id                  SERIAL          PRIMARY KEY,
    decision_id         INTEGER         NOT NULL UNIQUE REFERENCES decisions (id) ON DELETE RESTRICT,
    company_id          INTEGER         NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    price_at_decision   NUMERIC(14,2),
    price_at_outcome    NUMERIC(14,2),
    actual_return       NUMERIC(8,4),
    actual_weight       NUMERIC(6,4),
    is_correct          BOOLEAN,
    evaluation_note     TEXT,
    evaluated_at        TIMESTAMPTZ     NOT NULL,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_outcomes_decision  ON outcomes (decision_id);
CREATE INDEX idx_outcomes_company   ON outcomes (company_id);
CREATE INDEX idx_outcomes_correct   ON outcomes (is_correct);
CREATE INDEX idx_outcomes_evaluated ON outcomes (evaluated_at DESC);

-- ============================================================
-- 9. weight_history (가중치 변경 이력 — α × ε × cf)
-- ============================================================
CREATE TABLE weight_history (
    id                  SERIAL          PRIMARY KEY,
    entity_type         VARCHAR(20)     NOT NULL
                            CHECK (entity_type IN ('causal_edge', 'source')),
    entity_id           INTEGER         NOT NULL,
    weight_before       NUMERIC(6,4)    NOT NULL,
    weight_after        NUMERIC(6,4)    NOT NULL,
    delta               NUMERIC(6,4)    GENERATED ALWAYS AS (weight_after - weight_before) STORED,
    learning_rate       NUMERIC(5,4)    NOT NULL,
    error               NUMERIC(8,4),
    confidence_factor   NUMERIC(5,4),
    trigger_outcome_id  INTEGER         REFERENCES outcomes (id) ON DELETE SET NULL,
    changed_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wh_entity  ON weight_history (entity_type, entity_id);
CREATE INDEX idx_wh_changed ON weight_history (changed_at DESC);
CREATE INDEX idx_wh_outcome ON weight_history (trigger_outcome_id);

-- ============================================================
-- 10. positions (보유 포지션 — 모의/실전 공용)
-- ============================================================
CREATE TABLE positions (
    id              SERIAL          PRIMARY KEY,
    company_id      INTEGER         NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    mode            VARCHAR(10)     NOT NULL CHECK (mode IN ('paper', 'live')),
    quantity        INTEGER         NOT NULL DEFAULT 0,
    avg_buy_price   NUMERIC(14,2),
    unrealized_pnl  NUMERIC(14,2)   GENERATED ALWAYS AS (0.0) STORED,
    is_open         BOOLEAN         NOT NULL DEFAULT TRUE,
    opened_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_positions_company ON positions (company_id);
CREATE INDEX idx_positions_mode    ON positions (mode);
CREATE INDEX idx_positions_open    ON positions (is_open);

-- ============================================================
-- 11. trades (매매 체결 이력)
-- ============================================================
CREATE TABLE trades (
    id              SERIAL          PRIMARY KEY,
    position_id     INTEGER         REFERENCES positions (id) ON DELETE SET NULL,
    decision_id     INTEGER         REFERENCES decisions (id) ON DELETE SET NULL,
    company_id      INTEGER         NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    mode            VARCHAR(10)     NOT NULL CHECK (mode IN ('paper', 'live')),
    side            VARCHAR(5)      NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity        INTEGER         NOT NULL,
    price           NUMERIC(14,2)   NOT NULL,
    fee             NUMERIC(10,4)   NOT NULL DEFAULT 0,
    realized_pnl    NUMERIC(14,4),
    executed_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trades_company    ON trades (company_id);
CREATE INDEX idx_trades_mode       ON trades (mode);
CREATE INDEX idx_trades_executed   ON trades (executed_at DESC);
CREATE INDEX idx_trades_position   ON trades (position_id);
CREATE INDEX idx_trades_decision   ON trades (decision_id);

-- ============================================================
-- 12. backtest_sessions (버핏 블라인드 테스트 세션)
-- ============================================================
CREATE TABLE backtest_sessions (
    id              SERIAL          PRIMARY KEY,
    name            VARCHAR(200),
    sim_start_date  DATE            NOT NULL,
    sim_end_date    DATE            NOT NULL,
    initial_cash    NUMERIC(16,2)   NOT NULL,
    final_cash      NUMERIC(16,2),
    total_return    NUMERIC(8,4),
    benchmark_return NUMERIC(8,4),
    alpha           NUMERIC(8,4),
    sharpe_ratio    NUMERIC(8,4),
    max_drawdown    NUMERIC(8,4),
    total_trades    INTEGER,
    win_rate        NUMERIC(5,4),
    meta            JSONB,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bt_sessions_date ON backtest_sessions (sim_start_date, sim_end_date);

-- ============================================================
-- 13. backtest_trades (버핏 테스트 내 개별 매매)
-- ============================================================
CREATE TABLE backtest_trades (
    id              SERIAL          PRIMARY KEY,
    session_id      INTEGER         NOT NULL REFERENCES backtest_sessions (id) ON DELETE CASCADE,
    company_id      INTEGER         NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    side            VARCHAR(5)      NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity        INTEGER         NOT NULL,
    price           NUMERIC(14,2)   NOT NULL,
    realized_pnl    NUMERIC(14,4),
    trade_date      DATE            NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bt_trades_session ON backtest_trades (session_id);
CREATE INDEX idx_bt_trades_company ON backtest_trades (company_id);
CREATE INDEX idx_bt_trades_date    ON backtest_trades (trade_date);

-- ============================================================
-- TRIGGERS: updated_at 자동 갱신
-- ============================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sources_updated_at
    BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_causal_edges_updated_at
    BEFORE UPDATE ON causal_edges
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_positions_updated_at
    BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
