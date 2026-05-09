"""Reference data CRUD routes. Auth guard tests require DELETE /api/subjects/{id}."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import Subject, User
from app.routes.auth import require_admin

router = APIRouter(prefix="/api", tags=["reference"])


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(
    subject_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    try:
        sp = db.begin_nested()
        db.delete(subject)
        db.flush()
        sp.commit()
    except IntegrityError:
        sp.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete subject with dependent data")
