import os
import uuid
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(to_email, to_name, subject, html_content, reply_to=None):
    """
    Send a transactional email via Brevo SMTP (no IP whitelisting required).
    Returns (message_id, error_message).
    """
    smtp_user = os.environ.get('BREVO_SMTP_USER')
    smtp_pass = os.environ.get('BREVO_SMTP_PASS')
    sender_email = os.environ.get('BREVO_SENDER_EMAIL', 'hello@inventorsleague.co.uk')
    sender_name = os.environ.get('BREVO_SENDER_NAME', 'Inventors League')

    if not smtp_user or not smtp_pass:
        return None, 'BREVO_SMTP_USER / BREVO_SMTP_PASS not configured'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f'{sender_name} <{sender_email}>'
    msg['To'] = f'{to_name} <{to_email}>' if to_name else to_email
    if reply_to:
        msg['Reply-To'] = reply_to

    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP('smtp-relay.brevo.com', 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender_email, to_email, msg.as_string())
        message_id = f'<{uuid.uuid4()}@inventorsleague.co.uk>'
        return message_id, None
    except Exception as e:
        return None, str(e)
