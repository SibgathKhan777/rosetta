import resend

from app.core.config import settings

resend.api_key = settings.resend_api_key


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    resend.Emails.send(
        {
            "from": settings.resend_from_email,
            "to": [to_email],
            "subject": "Reset your Rosetta password",
            "html": (
                "<p>Someone requested a password reset for your Rosetta account.</p>"
                f'<p><a href="{reset_link}">Click here to reset your password</a></p>'
                f"<p>This link expires in {settings.password_reset_token_expire_minutes} minutes. "
                "If you didn't request this, you can safely ignore this email.</p>"
            ),
        }
    )
