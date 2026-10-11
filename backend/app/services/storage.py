"""Object storage for the original PDF and page images (never stored in PostgreSQL).

Keys look like:  books/<book-slug>/original.pdf,  books/<book-slug>/pages/0263.png

* local    - files under DATA_DIR (the ingestion pipeline renders straight into it); the API
             streams them from GET /api/v1/pages/{id}/image.
* supabase - Supabase Storage bucket. Uploads use the service-role key (backend only);
             the API redirects to a public or short-lived signed URL.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import settings


def page_image_key(book_slug: str, pdf_page: int) -> str:
    return f"books/{book_slug}/pages/{pdf_page:04d}.png"


def original_pdf_key(book_slug: str) -> str:
    return f"books/{book_slug}/original.pdf"


class LocalStorage:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def local_path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):  # defence against path traversal via crafted keys
            raise ValueError("Invalid storage key")
        return path

    def put_file(self, key: str, src: Path, content_type: str) -> None:
        dest = self.local_path(key)
        if dest == Path(src).resolve():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)

    def exists(self, key: str) -> bool:
        return self.local_path(key).exists()

    def public_url(self, key: str) -> str | None:
        return None  # served by the API


class SupabaseStorage:
    name = "supabase"

    def __init__(self) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for STORAGE_BACKEND=supabase")
        self.base = settings.supabase_url.rstrip("/") + "/storage/v1"
        self.bucket = settings.storage_bucket
        key = settings.supabase_service_role_key
        self._client = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {key}", "apikey": key})

    def ensure_bucket(self) -> None:
        r = self._client.get(f"{self.base}/bucket/{self.bucket}")
        if r.status_code == 200:
            return
        r = self._client.post(
            f"{self.base}/bucket", json={"id": self.bucket, "name": self.bucket, "public": settings.storage_public}
        )
        if r.status_code not in (200, 201, 409):
            r.raise_for_status()

    def put_file(self, key: str, src: Path, content_type: str) -> None:
        with open(src, "rb") as fh:
            r = self._client.post(
                f"{self.base}/object/{self.bucket}/{quote(key)}",
                content=fh.read(),
                headers={"Content-Type": content_type, "x-upsert": "true", "cache-control": "31536000"},
            )
        r.raise_for_status()

    def exists(self, key: str) -> bool:
        r = self._client.head(f"{self.base}/object/{self.bucket}/{quote(key)}")
        return r.status_code == 200

    def public_url(self, key: str) -> str | None:
        if settings.storage_public:
            return f"{self.base}/object/public/{self.bucket}/{quote(key)}"
        r = self._client.post(
            f"{self.base}/object/sign/{self.bucket}/{quote(key)}", json={"expiresIn": settings.storage_signed_url_ttl}
        )
        r.raise_for_status()
        signed = r.json().get("signedURL") or r.json().get("signedUrl")
        return f"{self.base}{signed}" if signed else None


@lru_cache
def get_storage() -> LocalStorage | SupabaseStorage:
    if settings.storage_backend == "supabase":
        return SupabaseStorage()
    return LocalStorage(Path(settings.data_dir) / "storage")
