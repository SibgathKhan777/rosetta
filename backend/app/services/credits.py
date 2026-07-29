import uuid

from sqlalchemy.orm import Session

from app.models.usage_credits import UsageCredits

# Cost scales roughly with video duration rather than a flat per-job charge.
# 1 credit per started minute of source video, minimum 1 credit. Duration is
# unknown at submission time (yt-dlp hasn't run yet), so submission only
# requires a nonzero balance; the real deduction happens once the download
# stage reports the actual duration (see app/workers/tasks.py).
# Billing/Stripe top-ups are not wired up yet — this only tracks a balance.
MIN_CREDITS_TO_SUBMIT = 1
CREDITS_PER_MINUTE = 1


def estimate_cost(duration_seconds: float) -> int:
    minutes = max(1, -(-int(duration_seconds) // 60))  # ceil division, min 1
    return minutes * CREDITS_PER_MINUTE


def deduct_credits(db: Session, user_id: uuid.UUID, cost: int) -> None:
    """Deduct the actual per-job cost once duration is known. Allowed to take
    a user's balance negative — a job already ran, so there's nothing to
    reject at this point; it just means their next submission is blocked
    until top-up (not implemented yet) or admin adjustment.
    """
    credits = db.get(UsageCredits, user_id)
    if credits is None:
        return
    credits.credits_remaining -= cost
    credits.credits_used_total += cost
    db.commit()
