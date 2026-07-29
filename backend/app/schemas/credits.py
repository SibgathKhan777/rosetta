from pydantic import BaseModel


class CreditsResponse(BaseModel):
    credits_remaining: int
    credits_used_total: int
