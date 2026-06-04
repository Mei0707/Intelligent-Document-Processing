from fastapi import APIRouter, Depends
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("", response_model=schemas.AnalyticsResponse)
def get_analytics(db: Session = Depends(get_db)):
    total = db.query(func.count(models.Document.id)).scalar() or 0

    def count_status(s: str) -> int:
        return (
            db.query(func.count(models.Document.id))
            .filter(models.Document.status == s)
            .scalar()
            or 0
        )

    by_cat_rows = (
        db.query(models.Document.category, func.count(models.Document.id))
        .filter(models.Document.category.isnot(None))
        .group_by(models.Document.category)
        .order_by(desc(func.count(models.Document.id)))
        .all()
    )
    by_category = [
        schemas.CategoryStat(category=cat or "Uncategorized", count=int(cnt))
        for cat, cnt in by_cat_rows
    ]

    recent = (
        db.query(models.Document)
        .order_by(desc(models.Document.uploaded_at))
        .limit(5)
        .all()
    )

    return {
        "total_documents": total,
        "processed": count_status("done"),
        "failed": count_status("failed"),
        "pending": count_status("pending") + count_status("processing"),
        "by_category": by_category,
        "recent": recent,
    }
