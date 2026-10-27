import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
APP_BASE_URL = os.getenv("APP_BASE_URL")


def send_reset_email(to_email, reset_link):
    msg = EmailMessage()
    msg["Subject"] = "Reset your eCamp password"
    msg["From"] = f"eCamp <{SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(
        "Click the link to reset your password. It expires in 30 minutes "
        f"and works once:\n{reset_link}\n\n"
        "If you didn't request this, ignore this email."
    )

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)