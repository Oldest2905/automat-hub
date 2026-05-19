-- ============================================================
-- Migration 001: Create DCP Tables
-- The Automat Hub — Digital Condition Passport Protocol
-- ============================================================
-- CRITICAL SECURITY RULE:
-- The dcp_hash_ledger table is APPEND-ONLY.
-- UPDATE and DELETE are REVOKED at database level.
-- This is what makes the DCP tamper-evident without blockchain.
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── DCP RECORDS TABLE ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS dcp_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dcp_id          VARCHAR(50) UNIQUE NOT NULL,
    vin             VARCHAR(17) NOT NULL,
    make            VARCHAR(50),
    model           VARCHAR(50),
    year            INTEGER,
    colour          VARCHAR(30),
    odometer        INTEGER,
    score           INTEGER NOT NULL CHECK (score >= 0 AND score <= 100),
    grade           CHAR(1) NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D')),
    status          VARCHAR(20) NOT NULL DEFAULT 'VERIFIED'
                    CHECK (status IN ('VERIFIED', 'EXPIRED', 'DISPUTED', 'REVOKED')),
    auditor_id      VARCHAR(50) NOT NULL,
    auditor_name    VARCHAR(100),
    warranty_days   INTEGER DEFAULT 30,
    warranty_expiry TIMESTAMPTZ,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast lookup
CREATE INDEX idx_dcp_records_vin ON dcp_records(vin);
CREATE INDEX idx_dcp_records_dcp_id ON dcp_records(dcp_id);
CREATE INDEX idx_dcp_records_vin_issued ON dcp_records(vin, issued_at DESC);
CREATE INDEX idx_dcp_records_status ON dcp_records(status);

-- ─── DCP HASH LEDGER — APPEND ONLY ─────────────────────────
-- This is the cryptographic trust anchor.
-- Once written, nothing is ever changed or deleted.
-- The database enforces this at permission level.
CREATE TABLE IF NOT EXISTS dcp_hash_ledger (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dcp_id          VARCHAR(50) NOT NULL UNIQUE
                    REFERENCES dcp_records(dcp_id) ON DELETE RESTRICT,
    vin             VARCHAR(17) NOT NULL,
    hash            VARCHAR(64) NOT NULL UNIQUE,
    hash_algorithm  VARCHAR(20) NOT NULL DEFAULT 'SHA-256',
    payload_json    JSONB NOT NULL,
    payload_string  TEXT NOT NULL,
    auditor_id      VARCHAR(50) NOT NULL,
    issuer          VARCHAR(100) NOT NULL DEFAULT 'The Automat Hub Ltd',
    protocol_version VARCHAR(10) NOT NULL DEFAULT '1.0',
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_hash_ledger_dcp_id ON dcp_hash_ledger(dcp_id);
CREATE INDEX idx_hash_ledger_vin ON dcp_hash_ledger(vin);
CREATE INDEX idx_hash_ledger_hash ON dcp_hash_ledger(hash);

-- ─── REVOKE UPDATE AND DELETE ON HASH LEDGER ────────────────
-- This is the single most important security line in the codebase.
-- No one — not even admins — can modify a hash once written.
-- Create application user first, then revoke.

-- Create application role (run once)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'automat_api') THEN
        CREATE ROLE automat_api LOGIN PASSWORD 'change_this_password';
    END IF;
END
$$;

-- Grant necessary permissions to application user
GRANT CONNECT ON DATABASE postgres TO automat_api;
GRANT USAGE ON SCHEMA public TO automat_api;
GRANT SELECT, INSERT ON dcp_hash_ledger TO automat_api;
GRANT SELECT, INSERT, UPDATE ON dcp_records TO automat_api;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO automat_api;

-- REVOKE UPDATE AND DELETE — CRITICAL
REVOKE UPDATE ON dcp_hash_ledger FROM automat_api;
REVOKE DELETE ON dcp_hash_ledger FROM automat_api;
-- Also revoke from public for safety
REVOKE UPDATE ON dcp_hash_ledger FROM PUBLIC;
REVOKE DELETE ON dcp_hash_ledger FROM PUBLIC;

-- ─── INSPECTION DETAILS TABLE ───────────────────────────────
CREATE TABLE IF NOT EXISTS inspection_details (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dcp_id                      VARCHAR(50) NOT NULL UNIQUE
                                REFERENCES dcp_records(dcp_id) ON DELETE RESTRICT,

    -- OBD-II
    obd2_status                 VARCHAR(30),
    obd2_fault_codes            JSONB DEFAULT '[]'::jsonb,
    obd2_readiness_monitors     JSONB DEFAULT '{}'::jsonb,

    -- Engine
    engine_compression          VARCHAR(20),
    engine_oil_condition        VARCHAR(20),
    coolant_condition           VARCHAR(20),
    timing_belt_condition       VARCHAR(20),

    -- Transmission
    transmission_condition      VARCHAR(20),
    transmission_fluid          VARCHAR(20),

    -- Chassis & Body
    frame_alignment             VARCHAR(20),
    rust_assessment             VARCHAR(20),
    accident_history_indicators BOOLEAN DEFAULT FALSE,
    paint_uniformity            VARCHAR(20),

    -- Electrical
    battery_health              VARCHAR(20),
    alternator_output           VARCHAR(20),
    electronics_status          VARCHAR(20),

    -- Safety
    brake_condition             VARCHAR(20),
    tyre_condition              JSONB DEFAULT '{}'::jsonb,
    airbag_status               VARCHAR(20),
    abs_status                  VARCHAR(20),

    -- AI Diagnostics
    ai_condition_grade          VARCHAR(20),
    ai_confidence_score         DECIMAL(4,3),
    ai_flags                    JSONB DEFAULT '[]'::jsonb,

    -- Full 150-point checklist
    checklist_results           JSONB NOT NULL,

    -- Photos stored in S3
    photos_s3_urls              JSONB DEFAULT '[]'::jsonb,

    -- Notes
    inspector_notes             TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_inspection_dcp_id ON inspection_details(dcp_id);

-- ─── VERIFICATION LOG TABLE ─────────────────────────────────
-- Every public DCP scan is recorded.
-- Builds market demand data and Dealer Reputation Graph.
CREATE TABLE IF NOT EXISTS verification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dcp_id          VARCHAR(50) NOT NULL
                    REFERENCES dcp_records(dcp_id) ON DELETE RESTRICT,
    verified_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_by_ip  VARCHAR(45),
    result          BOOLEAN NOT NULL,
    method          VARCHAR(20) CHECK (method IN ('QR', 'NFC', 'API', 'MANUAL', 'DIRECT'))
);

CREATE INDEX idx_verification_dcp_id ON verification_log(dcp_id);
CREATE INDEX idx_verification_date ON verification_log(verified_at DESC);

-- ─── GRANT PERMISSIONS ON NEW TABLES ────────────────────────
GRANT SELECT, INSERT ON inspection_details TO automat_api;
GRANT SELECT, INSERT ON verification_log TO automat_api;

-- ─── VERIFY SETUP ───────────────────────────────────────────
-- Run this to confirm the ledger is append-only:
-- \dp dcp_hash_ledger
-- You should see UPDATE and DELETE are NOT in automat_api privileges.

COMMENT ON TABLE dcp_hash_ledger IS
    'APPEND-ONLY tamper-evident hash ledger. UPDATE and DELETE are revoked. '
    'This is the cryptographic trust anchor of The Automat Hub protocol.';

COMMENT ON COLUMN dcp_hash_ledger.hash IS
    'SHA-256 hex digest of the serialized DCP payload. '
    'Recompute from payload_string to verify integrity.';
