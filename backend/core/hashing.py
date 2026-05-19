"""
core/hashing.py
SHA-256 cryptographic hashing engine for DCP records.
This is the trust core of the entire protocol.

Every DCP record is hashed at the moment of issuance.
The hash is stored in an append-only ledger table.
Any tampering with inspection data produces a different hash.
This makes every DCP cryptographically tamper-evident.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


def serialize_payload(data: dict) -> str:
    """
    Serialize inspection data to a canonical JSON string.
    sort_keys=True ensures key order is always identical.
    This is critical — different key order = different hash.
    separators removes whitespace for deterministic output.
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        default=str  # handles datetime serialization
    )


def generate_sha256(payload_string: str) -> str:
    """
    Generate SHA-256 hash from a string payload.
    Returns 64-character hex digest.
    """
    return hashlib.sha256(
        payload_string.encode('utf-8')
    ).hexdigest()


def generate_dcp_id() -> str:
    """
    Generate a unique DCP identifier.
    Format: ATH-YYYY-XXXXXXXX
    Example: ATH-2026-A3F9B201
    """
    year = datetime.now(timezone.utc).year
    unique_suffix = str(uuid.uuid4()).replace('-', '').upper()[:8]
    return f"ATH-{year}-{unique_suffix}"


def build_dcp_payload(
    dcp_id: str,
    vin: str,
    auditor_id: str,
    inspection_data: dict,
    issued_at: datetime
) -> dict:
    """
    Build the complete DCP payload that will be hashed.
    This exact structure must be preserved — any change
    to this structure will invalidate existing hashes.
    """
    return {
        "protocol_version": "1.0",
        "issuer": "The Automat Hub Ltd",
        "issuer_rc": "RC9129839",
        "dcp_id": dcp_id,
        "issued_at": issued_at.isoformat(),
        "auditor_id": auditor_id,
        "vehicle": {
            "vin": vin,
        },
        "inspection": inspection_data,
    }


def issue_dcp_hash(
    vin: str,
    auditor_id: str,
    inspection_data: dict
) -> dict:
    """
    Main function to issue a DCP hash record.

    Returns complete hash record ready for database storage.

    Usage:
        record = issue_dcp_hash(
            vin="1C4HJXDN0MW524170",
            auditor_id="ATH-QA-084",
            inspection_data={...}
        )
    """
    dcp_id = generate_dcp_id()
    issued_at = datetime.now(timezone.utc)

    # Build canonical payload
    payload = build_dcp_payload(
        dcp_id=dcp_id,
        vin=vin,
        auditor_id=auditor_id,
        inspection_data=inspection_data,
        issued_at=issued_at
    )

    # Serialize and hash
    payload_string = serialize_payload(payload)
    sha256_hash = generate_sha256(payload_string)

    return {
        "dcp_id": dcp_id,
        "vin": vin,
        "auditor_id": auditor_id,
        "issued_at": issued_at,
        "payload": payload,
        "payload_string": payload_string,
        "hash": sha256_hash,
        "hash_algorithm": "SHA-256",
        "verification_url": f"https://automatcorp.org.ng/verify/{dcp_id}",
    }


def verify_dcp_hash(
    stored_hash: str,
    stored_payload: dict
) -> dict:
    """
    Verify a DCP record has not been tampered with.

    Recomputes the hash from stored payload.
    Compares with stored hash.
    Returns verification result with details.

    Usage:
        result = verify_dcp_hash(
            stored_hash="e3b0c44...",
            stored_payload={...}
        )
    """
    payload_string = serialize_payload(stored_payload)
    recomputed_hash = generate_sha256(payload_string)

    is_valid = recomputed_hash == stored_hash

    return {
        "is_valid": is_valid,
        "stored_hash": stored_hash,
        "recomputed_hash": recomputed_hash,
        "hashes_match": is_valid,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "SHA-256",
        "tamper_evident": True,
        "status": "VERIFIED" if is_valid else "TAMPERED"
    }


def quick_verify(stored_hash: str, stored_payload: dict) -> bool:
    """
    Quick boolean verification for internal use.
    """
    payload_string = serialize_payload(stored_payload)
    recomputed_hash = generate_sha256(payload_string)
    return recomputed_hash == stored_hash
