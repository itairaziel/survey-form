#!/usr/bin/env python3
"""
Hermes Gmail Agent
מאפשר לHermes לקרוא ולנתח מיילים מGmail
"""

import os
import json
import anthropic
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
import pickle

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
CREDENTIALS_PATH = os.path.expanduser('~/.gmail-mcp/gcp-oauth.keys.json')
TOKEN_PATH = os.path.expanduser('~/.gmail-mcp/token.pkl')
MODEL = 'claude-haiku-4-5-20251001'


def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'wb') as f:
            pickle.dump(creds, f)

    return build('gmail', 'v1', credentials=creds)


def get_emails(service, max_results=10, query=''):
    results = service.users().messages().list(
        userId='me', maxResults=max_results, q=query
    ).execute()
    messages = results.get('messages', [])

    emails = []
    for msg in messages:
        full = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        headers = {h['name']: h['value'] for h in full['payload'].get('headers', [])}
        subject = headers.get('Subject', '(no subject)')
        sender = headers.get('From', '')
        date = headers.get('Date', '')

        body = ''
        payload = full['payload']
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    break
        elif 'body' in payload:
            data = payload['body'].get('data', '')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

        emails.append({
            'subject': subject,
            'from': sender,
            'date': date,
            'body': body[:2000]  # limit body length
        })

    return emails


def ask_hermes(messages):
    client = anthropic.Anthropic()
    system_messages = [m['content'] for m in messages if m['role'] == 'system']
    chat_messages = [m for m in messages if m['role'] != 'system']
    system_text = '\n'.join(system_messages) if system_messages else f'אתה עוזר אישי בשם Hermes. אתה רץ על מודל {MODEL} של Anthropic.'
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_text,
        messages=chat_messages,
    )
    return response.content[0].text


def format_emails_for_context(emails):
    text = "להלן המיילים:\n\n"
    for i, email in enumerate(emails, 1):
        text += f"--- מייל {i} ---\n"
        text += f"מאת: {email['from']}\n"
        text += f"תאריך: {email['date']}\n"
        text += f"נושא: {email['subject']}\n"
        text += f"תוכן:\n{email['body']}\n\n"
    return text


def main():
    print("מתחבר לGmail...")
    service = get_gmail_service()
    print("מחובר!")

    conversation = []

    while True:
        user_input = input("\nשאל את Hermes: ").strip()
        if not user_input or user_input.lower() in ['exit', 'quit', 'יציאה']:
            break

        # אם המשתמש מבקש מיילים, נטען אותם
        if any(w in user_input.lower() for w in ['מייל', 'אימייל', 'inbox', 'mail', 'email']):
            print("טוען מיילים...")
            emails = get_emails(service, max_results=5)
            email_context = format_emails_for_context(emails)

            conversation.append({
                'role': 'system',
                'content': f'אתה עוזר שמנתח מיילים של המשתמש. {email_context}'
            })

        conversation.append({'role': 'user', 'content': user_input})

        print("Hermes חושב...")
        response = ask_hermes(conversation)
        conversation.append({'role': 'assistant', 'content': response})

        print(f"\nHermes: {response}")


if __name__ == '__main__':
    main()
