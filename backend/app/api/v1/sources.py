from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.citation.verify import load_sources
from app.core.database import get_db
from app.schemas.source import SourceOut

router = APIRouter(tags=["sources"])


@router.get("/sources/{source_id}", response_model=SourceOut, summary="Verified source passage by stable id")
def get_source(
    source_id: str = Path(pattern=r"^chunk_[0-9a-f]{10}$"),
    db: Session = Depends(get_db),
) -> SourceOut:
    found = load_sources(db, [source_id])
    if source_id not in found:
        raise HTTPException(status_code=404, detail="Source not found")
    return found[source_id]
