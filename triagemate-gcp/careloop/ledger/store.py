"""Ledger persistence: local JSON (default) or Firestore.

Choose the backend with the CARELOOP_STORE environment variable:

    local      (default)  ->  ledgers/<patient_id>.json on disk
    firestore             ->  a Firestore collection, one document per patient

Both backends expose the same functions, keyed by patient_id, so ingest.py
and the agent's ledger tools never care which is active. Local stays the
default on purpose: the offline path must never break. Switch to Firestore
only once the API is enabled and credentials work (see CARELOOP_MASTER.md).

Why keyed by patient_id and not a file path: Firestore has no paths. Making
patient_id the key lets the same two calls work against a file or a
database with no change upstream.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .schema import Ledger

STORE = os.getenv("CARELOOP_STORE", "local").lower()
LEDGER_DIR = os.getenv("CARELOOP_LEDGER_DIR", "ledgers")
FS_COLLECTION = os.getenv("CARELOOP_FS_COLLECTION", "ledgers")


# --------------------------------------------------------------------------
# Public API (backend-agnostic)
# --------------------------------------------------------------------------
def load_ledger(patient_id: str, patient_name: str = "") -> Ledger:
    """Load a patient's ledger, or a fresh empty one if none exists yet."""
    if STORE == "firestore":
        return _fs_load(patient_id, patient_name)
    return _local_load(patient_id, patient_name)


def save_ledger(ledger: Ledger) -> None:
    """Persist a ledger under its patient_id."""
    if STORE == "firestore":
        _fs_save(ledger)
    else:
        _local_save(ledger)


def ledger_exists(patient_id: str) -> bool:
    """True if a ledger is already on file for this patient."""
    if STORE == "firestore":
        return _fs_exists(patient_id)
    return _local_path(patient_id).exists()


def list_patients() -> list[str]:
    """All patient ids that have a ledger on file."""
    if STORE == "firestore":
        return _fs_list()
    base = Path(LEDGER_DIR)
    return sorted(p.stem for p in base.glob("*.json")) if base.is_dir() else []


def backend_name() -> str:
    """Human-readable description of the active backend, for logging."""
    if STORE == "firestore":
        return f"Firestore collection '{FS_COLLECTION}'"
    return f"local JSON in '{LEDGER_DIR}/'"


# --------------------------------------------------------------------------
# Local JSON backend
# --------------------------------------------------------------------------
def _local_path(patient_id: str) -> Path:
    return Path(LEDGER_DIR) / f"{patient_id}.json"


def _local_load(patient_id: str, patient_name: str = "") -> Ledger:
    path = _local_path(patient_id)
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            return Ledger.from_dict(json.load(handle))
    return Ledger(patient_id=patient_id, patient_name=patient_name)


def _local_save(ledger: Ledger) -> None:
    path = _local_path(ledger.patient_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(ledger.to_dict(), handle, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# Firestore backend
# --------------------------------------------------------------------------
def _fs_client():
    try:
        from google.cloud import firestore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "CARELOOP_STORE=firestore needs the client library. Install it:\n"
            "    pip install google-cloud-firestore\n"
            "Or unset CARELOOP_STORE to use the local JSON store."
        ) from exc
    database = os.getenv("CARELOOP_FS_DATABASE")
    return firestore.Client(database=database) if database else firestore.Client()


def _fs_doc(patient_id: str):
    return _fs_client().collection(FS_COLLECTION).document(patient_id)


def _fs_load(patient_id: str, patient_name: str = "") -> Ledger:
    snap = _fs_doc(patient_id).get()
    if snap.exists:
        return Ledger.from_dict(snap.to_dict())
    return Ledger(patient_id=patient_id, patient_name=patient_name)


def _fs_save(ledger: Ledger) -> None:
    _fs_doc(ledger.patient_id).set(ledger.to_dict())


def _fs_exists(patient_id: str) -> bool:
    return _fs_doc(patient_id).get().exists


def _fs_list() -> list[str]:
    docs = _fs_client().collection(FS_COLLECTION).stream()
    return sorted(doc.id for doc in docs)
