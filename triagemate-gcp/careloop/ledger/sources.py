"""Where documents come from.

Today: a local folder. Reads .txt and .md directly, and .pdf via pypdf if
a real report is dropped in. Each document is fingerprinted (SHA-256 of its
text) so the compaction step can skip anything already ingested.

Next (Day 4/5): a Google Drive source yielding the same (filename, text,
hash) tuples, so the ingest pipeline does not change. The simplest Drive
path -- and the one to use -- is a SERVICE ACCOUNT with a shared folder:
create a service account, share one Drive folder with its email, and it
reads the folder with no OAuth consent screen. That avoids the user-consent
dance entirely, which is the part that eats a day. Sketch at the bottom.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

TEXT_SUFFIXES = {".txt", ".md"}
SUPPORTED = TEXT_SUFFIXES | {".pdf"}


@dataclass
class SourceDocument:
    filename: str
    text: str
    content_hash: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Reading PDFs needs pypdf. Install it with: pip install pypdf. "
            "Or test with .txt sample documents, which need nothing extra."
        ) from exc
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_local_folder(folder: Path | str) -> Iterator[SourceDocument]:
    """Yield every supported document in a folder, sorted by name.

    Sorting by filename gives a stable ingestion order. Since documents in
    this project are named with their date prefix, that also happens to be
    chronological -- though the merge sorts lab series by date regardless,
    so order does not affect the result.
    """
    base = Path(folder)
    if not base.is_dir():
        raise FileNotFoundError(f"Not a folder: {base}")

    for path in sorted(base.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore")
        else:
            text = _read_pdf(path)
        yield SourceDocument(
            filename=path.name,
            text=text,
            content_hash=_hash(text),
        )


# --- Google Drive drop-in, for Day 4/5 (service-account + shared folder) ----
#
# from googleapiclient.discovery import build
# from google.oauth2 import service_account
#
# SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
#
# def read_drive_folder(folder_id, key_file="service_account.json"):
#     creds = service_account.Credentials.from_service_account_file(
#         key_file, scopes=SCOPES)
#     svc = build("drive", "v3", credentials=creds)
#     files = svc.files().list(
#         q=f"'{folder_id}' in parents and trashed=false",
#         fields="files(id, name, mimeType)").execute().get("files", [])
#     for f in files:
#         # export Google Docs as text; download PDFs and extract; etc.
#         # yield SourceDocument(filename=f["name"], text=..., content_hash=...)
#         ...
#
# Setup, once:
#   1. gcloud iam service-accounts create careloop-drive
#   2. download its JSON key -> service_account.json (gitignored)
#   3. share the target Drive folder with the service account's email
#   4. pass the folder id (from the Drive URL) as folder_id
