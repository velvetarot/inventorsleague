import os
import requests

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'


def send_email(to_email, to_name, subject, html_content, reply_to=None):
    """
    Send a transactional email via Brevo.
    Returns (message_id, error_message).
    message_id is None if sending failed.
    """
    api_key = os.environ.get('BREVO_API_KEY')
    sender_email = os.environ.get('BREVO_SENDER_EMAIL', 'hello@inventorsleague.co.uk')
    sender_name = os.environ.get('BREVO_SENDER_NAME', 'Inventors League')

    if not api_key:
        return None, 'BREVO_API_KEY not configured'

    payload = {
        'sender': {'name': sender_name, 'email': sender_email},
        'to': [{'email': to_email, 'name': to_name or to_email}],
        'subject': subject,
        'htmlContent': html_content,
    }
    if reply_to:
        payload['replyTo'] = {'email': reply_to}

    headers = {
        'accept': 'application/json',
        'api-key': api_key,
        'content-type': 'application/json',
    }

    try:
        r = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=10)
        if r.status_code == 201:
            message_id = r.json().get('messageId', '')
            return message_id, None
        else:
            return None, f'Brevo error {r.status_code}: {r.text}'
    except Exception as e:
        return None, str(e)
