import os
import json
import httpx
import base64
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from app.core.config import settings

ACTIVE_GOOGLE_OAUTH_TOKEN: Optional[str] = None
ACTIVE_GOOGLE_REFRESH_TOKEN: Optional[str] = None

# Persistent token storage file path
TOKEN_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".google_tokens.json")


def save_tokens_to_file(token: str, refresh_token: Optional[str] = None):
    """Saves OAuth tokens to disk so server reloads do not lose authentication."""
    global ACTIVE_GOOGLE_OAUTH_TOKEN, ACTIVE_GOOGLE_REFRESH_TOKEN
    ACTIVE_GOOGLE_OAUTH_TOKEN = token
    if refresh_token:
        ACTIVE_GOOGLE_REFRESH_TOKEN = refresh_token

    data = {
        "access_token": ACTIVE_GOOGLE_OAUTH_TOKEN,
        "refresh_token": ACTIVE_GOOGLE_REFRESH_TOKEN,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        with open(TOKEN_FILE_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_tokens_from_file():
    """Loads saved OAuth tokens from disk on server startup."""
    global ACTIVE_GOOGLE_OAUTH_TOKEN, ACTIVE_GOOGLE_REFRESH_TOKEN
    if os.path.exists(TOKEN_FILE_PATH):
        try:
            with open(TOKEN_FILE_PATH, "r") as f:
                data = json.load(f)
                ACTIVE_GOOGLE_OAUTH_TOKEN = data.get("access_token")
                if data.get("refresh_token"):
                    ACTIVE_GOOGLE_REFRESH_TOKEN = data.get("refresh_token")
        except Exception:
            pass


def set_google_oauth_token(token: str, refresh_token: Optional[str] = None):
    save_tokens_to_file(token, refresh_token)


def get_google_oauth_token() -> Optional[str]:
    global ACTIVE_GOOGLE_OAUTH_TOKEN
    if not ACTIVE_GOOGLE_OAUTH_TOKEN:
        load_tokens_from_file()
    return ACTIVE_GOOGLE_OAUTH_TOKEN


async def refresh_google_access_token() -> Optional[str]:
    """Uses refresh token to obtain a fresh access token silently from Google OAuth endpoint."""
    global ACTIVE_GOOGLE_OAUTH_TOKEN, ACTIVE_GOOGLE_REFRESH_TOKEN
    if not ACTIVE_GOOGLE_REFRESH_TOKEN:
        load_tokens_from_file()

    if not ACTIVE_GOOGLE_REFRESH_TOKEN:
        return None

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": ACTIVE_GOOGLE_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                new_access_token = data.get("access_token")
                if new_access_token:
                    save_tokens_to_file(new_access_token, ACTIVE_GOOGLE_REFRESH_TOKEN)
                    return new_access_token
    except Exception:
        pass
    return None


def create_raw_email(to: str, subject: str, body: str) -> str:
    """Constructs a base64url encoded RFC 2822 email for Gmail API."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return raw


async def execute_mcp_tool(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Universal FastMCP tool execution router supporting real Google Calendar and Gmail API execution.
    Auto-refreshes Google OAuth access token from disk or refresh token silently.
    """
    token = get_google_oauth_token()
    
    # If no token in memory or file, attempt silent refresh using refresh_token
    if not token and ACTIVE_GOOGLE_REFRESH_TOKEN:
        token = await refresh_google_access_token()

    if not token:
        login_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={settings.GOOGLE_CLIENT_ID}&redirect_uri={settings.GOOGLE_REDIRECT_URI}&response_type=code&scope=https://www.googleapis.com/auth/gmail.compose%20https://www.googleapis.com/auth/calendar&access_type=offline&prompt=consent"
        return {
            "status": "error",
            "message": f"🔑 Google OAuth session not authenticated. Please [Click Here to Sign in with Google]({login_url}) to grant initial access once."
        }

    headers = {"Authorization": f"Bearer {token}"}

    # 1. GMAIL API — Send Email
    if tool_name == "send_email":
        recipient = tool_args.get("recipient") or tool_args.get("to")
        subject = tool_args.get("subject") or "Notification from Alex AI"
        body = tool_args.get("body") or f"Hi,\n\n{tool_args.get('input_text', 'Notification message.')}\n\nBest regards,\nAlex AI Assistant"

        if not recipient:
            return {"status": "error", "message": "No recipient email address provided."}

        try:
            raw_email = create_raw_email(recipient, subject, body)
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                    headers=headers,
                    json={"raw": raw_email}
                )
                
                # If 401 Unauthorized, attempt silent token refresh once
                if resp.status_code == 401:
                    new_token = await refresh_google_access_token()
                    if new_token:
                        resp = await client.post(
                            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                            headers={"Authorization": f"Bearer {new_token}"},
                            json={"raw": raw_email}
                        )

                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "status": "success",
                        "message": f"✅ REAL Email sent to {recipient} via Gmail API! (Subject: '{subject}', Message ID: {data.get('id')})",
                        "email_id": data.get("id")
                    }
                else:
                    login_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={settings.GOOGLE_CLIENT_ID}&redirect_uri={settings.GOOGLE_REDIRECT_URI}&response_type=code&scope=https://www.googleapis.com/auth/gmail.compose%20https://www.googleapis.com/auth/calendar&access_type=offline&prompt=consent"
                    return {
                        "status": "error", 
                        "message": f"🔑 Google session expired. Please [Click Here to Sign In with Google]({login_url}) to grant access."
                    }
        except Exception as e:
            return {"status": "error", "message": f"Error sending email: {str(e)}"}

    # 2. GOOGLE CALENDAR API — Create Event
    elif tool_name == "create_calendar_event":
        title = tool_args.get("title") or "Meeting"
        recipient = tool_args.get("recipient") or tool_args.get("to")
        date_val = tool_args.get("date", datetime.now().strftime("%Y-%m-%d"))
        start_time_val = tool_args.get("start_time", "09:00:00")
        end_time_val = tool_args.get("end_time", "10:00:00")

        start_iso = f"{date_val}T{start_time_val}+05:30"
        end_iso = f"{date_val}T{end_time_val}+05:30"

        event_payload = {
            "summary": title,
            "description": f"Scheduled by Alex AI Assistant.",
            "start": {"dateTime": start_iso, "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end_iso, "timeZone": "Asia/Kolkata"},
        }
        if recipient:
            event_payload["attendees"] = [{"email": recipient}]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers=headers,
                    json=event_payload
                )

                if resp.status_code == 401:
                    new_token = await refresh_google_access_token()
                    if new_token:
                        resp = await client.post(
                            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                            headers={"Authorization": f"Bearer {new_token}"},
                            json=event_payload
                        )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    email_result = ""
                    if recipient:
                        email_res = await execute_mcp_tool("send_email", {
                            "recipient": recipient,
                            "subject": f"Meeting Invitation: {title}",
                            "body": f"Hi,\n\nYour meeting '{title}' has been scheduled on Google Calendar for {date_val} ({start_time_val} - {end_time_val} IST).\n\nCalendar Link: {data.get('htmlLink')}\n\nBest regards,\nAlex AI Assistant"
                        })
                        email_result = f" & {email_res.get('message')}"

                    return {
                        "status": "success",
                        "message": f"📅 REAL Google Calendar Event created for '{title}' on {date_val}! Link: {data.get('htmlLink')}{email_result}",
                        "event_id": data.get("id"),
                        "html_link": data.get("htmlLink")
                    }
                else:
                    login_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={settings.GOOGLE_CLIENT_ID}&redirect_uri={settings.GOOGLE_REDIRECT_URI}&response_type=code&scope=https://www.googleapis.com/auth/gmail.compose%20https://www.googleapis.com/auth/calendar&access_type=offline&prompt=consent"
                    return {
                        "status": "error", 
                        "message": f"🔑 Google session expired. Please [Click Here to Sign In with Google]({login_url}) to grant access."
                    }
        except Exception as e:
            return {"status": "error", "message": f"Error creating event: {str(e)}"}

    # Default fallbacks
    return {
        "status": "success",
        "message": f"Processed request for tool '{tool_name}' with parameters {tool_args}."
    }
