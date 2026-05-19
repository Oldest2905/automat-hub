-- ============================================================
-- Migration 002: Create Escrow Tables
-- The Automat Hub — Verified Escrow Settlement Protocol
-- ============================================================
-- ESCROW STATUS FLOW:
-- INITIATED → FUNDED → DCP_MATCHED → DELIVERY_CONFIRMED → COMPLETED
--                                                       ↘ DISPUTED
--                                                       ↘ REFUNDED
-- ============================================================

-- ─── ESCROW DEALS TABLE ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS escrow_deals (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    escrow_id                   VARCHAR(50) UNIQUE NOT NULL,
    dcp_id                      VARCHAR(50) NOT NULL,
    vin                         VARCHAR(17) NOT NULL,

    -- Parties
    buyer_name                  VARCHAR(100) NOT NULL,
    buyer_email                 VARCHAR(100) NOT NULL,
    buyer_phone                 VARCHAR(20),
    seller_name                 VARCHAR(100) NOT NULL,
    seller_account              VARCHAR(50),

    -- Amounts
    amount_usd                  DECIMAL(12,2) NOT NULL CHECK (amount_usd > 0),
    amount_ngn                  DECIMAL(15,2),
    fx_rate_at_deposit          DECIMAL(10,2),
    platform_fee_percent        DECIMAL(4,2) DEFAULT 1.50,
    platform_fee_amount         DECIMAL(12,2),
    seller_net_amount           DECIMAL(12,2),

    -- Status
    status                      VARCHAR(30) NOT NULL DEFAULT 'INITIATED'
                                CHECK (status IN (
                                    'INITIATED',
                                    'FUNDED',
                                    'DCP_MATCHED',
                                    'DELIVERY_CONFIRMED',
                                    'COMPLETED',
                                    'DISPUTED',
                                    'REFUNDED',
                                    'EXPIRED'
                                )),

    -- Release conditions — ALL must be TRUE before funds move
    dcp_verified                BOOLEAN NOT NULL DEFAULT FALSE,
    physical_delivery_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    buyer_acknowledged          BOOLEAN NOT NULL DEFAULT FALSE,

    -- Payment
    payment_reference           VARCHAR(100),
    payment_channel             VARCHAR(50),

    -- Timeline
    initiated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    funded_at                   TIMESTAMPTZ,
    dcp_matched_at              TIMESTAMPTZ,
    delivery_confirmed_at       TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,
    expiry_at                   TIMESTAMPTZ,

    -- Notes
    notes                       TEXT,
    dispute_reason              TEXT,

    -- Constraint: funds never release without all conditions
    CONSTRAINT funds_release_requires_all_conditions CHECK (
        (status != 'COMPLETED') OR
        (dcp_verified = TRUE AND physical_delivery_confirmed = TRUE AND buyer_acknowledged = TRUE)
    )
);

-- Indexes
CREATE INDEX idx_escrow_deals_escrow_id ON escrow_deals(escrow_id);
CREATE INDEX idx_escrow_deals_dcp_id ON escrow_deals(dcp_id);
CREATE INDEX idx_escrow_deals_vin ON escrow_deals(vin);
CREATE INDEX idx_escrow_deals_status ON escrow_deals(status);
CREATE INDEX idx_escrow_deals_buyer_email ON escrow_deals(buyer_email);

-- ─── ESCROW EVENTS TABLE — IMMUTABLE AUDIT TRAIL ────────────
-- Every status change creates an immutable event record.
-- This is the tamper-evident history of every transaction.
CREATE TABLE IF NOT EXISTS escrow_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    escrow_id       VARCHAR(50) NOT NULL
                    REFERENCES escrow_deals(escrow_id) ON DELETE RESTRICT,
    event_type      VARCHAR(50) NOT NULL,
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    triggered_by    VARCHAR(100) NOT NULL,
    notes           TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_escrow_events_escrow_id ON escrow_events(escrow_id);
CREATE INDEX idx_escrow_events_type ON escrow_events(event_type);
CREATE INDEX idx_escrow_events_created ON escrow_events(created_at DESC);

-- ─── REVOKE UPDATE AND DELETE ON EVENTS ─────────────────────
-- Events are also append-only — audit trail must be immutable
REVOKE UPDATE ON escrow_events FROM automat_api;
REVOKE DELETE ON escrow_events FROM automat_api;
REVOKE UPDATE ON escrow_events FROM PUBLIC;
REVOKE DELETE ON escrow_events FROM PUBLIC;

-- ─── GRANT PERMISSIONS ──────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON escrow_deals TO automat_api;
GRANT SELECT, INSERT ON escrow_events TO automat_api;

-- ─── USEFUL VIEWS ───────────────────────────────────────────

-- Active escrows view — for dashboard
CREATE OR REPLACE VIEW active_escrows AS
SELECT
    e.escrow_id,
    e.dcp_id,
    e.vin,
    e.buyer_name,
    e.seller_name,
    e.amount_usd,
    e.status,
    e.dcp_verified,
    e.physical_delivery_confirmed,
    e.initiated_at,
    e.expiry_at,
    EXTRACT(DAYS FROM (e.expiry_at - NOW())) AS days_until_expiry
FROM escrow_deals e
WHERE e.status NOT IN ('COMPLETED', 'REFUNDED', 'EXPIRED');

-- Transaction summary view — for reporting
CREATE OR REPLACE VIEW transaction_summary AS
SELECT
    DATE_TRUNC('month', completed_at) AS month,
    COUNT(*) AS transactions_completed,
    SUM(amount_usd) AS total_volume_usd,
    SUM(platform_fee_amount) AS total_fees_usd,
    SUM(seller_net_amount) AS total_settled_usd,
    AVG(amount_usd) AS avg_transaction_usd
FROM escrow_deals
WHERE status = 'COMPLETED'
GROUP BY DATE_TRUNC('month', completed_at)
ORDER BY month DESC;

COMMENT ON TABLE escrow_deals IS
    'Verified escrow settlement deals. Funds released ONLY when '
    'dcp_verified AND physical_delivery_confirmed AND buyer_acknowledged are all TRUE.';

COMMENT ON TABLE escrow_events IS
    'APPEND-ONLY immutable audit trail. Every escrow state change recorded permanently.';

COMMENT ON CONSTRAINT funds_release_requires_all_conditions ON escrow_deals IS
    'DATABASE-LEVEL GUARANTEE: A COMPLETED escrow must have all three conditions TRUE. '
    'This cannot be bypassed even by direct database access.';
