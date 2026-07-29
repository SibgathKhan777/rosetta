from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.usage_credits import UsageCredits
from app.models.user import User
from app.schemas.credits import CreditsResponse

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("", response_model=CreditsResponse)
def get_credits(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    credits = db.get(UsageCredits, user.id)
    if credits is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No credits record for this user")
    return CreditsResponse(
        credits_remaining=credits.credits_remaining,
        credits_used_total=credits.credits_used_total,
    )
