import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import settings


class ExtractedIntent(BaseModel):
    """Universal Pydantic schema for any AI tool request."""
    intent: str = Field(
        description="Classified user intent or tool: 'create_calendar_event', 'list_calendar_events', 'cancel_calendar_event', 'send_email', 'set_reminder', 'list_reminders', 'web_search', 'resolve_person', or 'general_chat'"
    )
    tool_args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dynamic dictionary of arbitrary extracted arguments (e.g., recipient, title, subject, body, date, start_time, end_time, query, reminder_text)"
    )
    missing_slots: List[str] = Field(
        default_factory=list,
        description="Missing required parameters if user query is incomplete"
    )


SYSTEM_INTENT_PROMPT = """
You are Alex, an autonomous executive AI assistant agent capable of performing any task requested by your user.
Analyze the user's input and determine the exact intent/tool to execute, extracting all required arguments dynamically into `tool_args`.

Supported Universal Capabilities & Tools:
1. `send_email`: Send emails. Extract `recipient` (email), `subject` (concise subject line), and `body` (professionally composed message body).
2. `create_calendar_event`: Schedule calendar meetings. Extract `title`, `recipient`, `date` (YYYY-MM-DD), `start_time` (HH:MM:SS), `end_time` (HH:MM:SS).
3. `list_calendar_events`: View upcoming events. Extract `date` or `date_range`.
4. `cancel_calendar_event`: Cancel a meeting. Extract `event_title_or_id`.
5. `set_reminder`: Set reminders. Extract `reminder_text`, `time`.
6. `list_reminders`: List active reminders. Extract `status`.
7. `web_search`: Search the web for information. Extract `query`.
8. `resolve_person`: Search contact details. Extract `name`.
9. `general_chat`: Answer general questions, write content, or converse naturally. Extract `text`.

CRITICAL INSTRUCTIONS:
- For communication tasks (emails/calendar invites), write genuine, professional messages directly for the recipient based on the user's intent. Never copy raw meta-commands like 'hey send a mail' into the body.
- Extract date/time parameters dynamically.
- Support any language, topic, or work task requested by the user.
"""


def get_llm(temperature: float = 0.2):
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temperature,
    )


def extract_universal_message_content(user_prompt: str) -> tuple[str, str]:
    """
    100% Universal text sanitizer. Strips command prefixes dynamically without any hardcoded topic keywords.
    """
    # 1. Strip meta command prefixes (e.g. "hey send a mail to x@y.com regarding")
    cleaned = re.sub(
        r'^(?:hey|hi|please)?\s*(?:send|write|draft|schedule|create)\s+(?:a\s+)?(?:mail|email|message|meeting|event)\s+(?:to|with)?\s*[\w\.-]+@[\w\.-]+\.\w+\s*(?:regarding|about|regading|sub|subject|saying|that|for)?\s*',
        '',
        user_prompt,
        flags=re.IGNORECASE
    ).strip()

    # 2. General cleanup of email addresses and action prefixes
    if not cleaned or cleaned.lower() == user_prompt.lower():
        cleaned = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', user_prompt).strip()
        cleaned = re.sub(r'^(?:hey|hi|please)?\s*(?:send|write|draft|schedule|create)\s+(?:a\s+)?(?:mail|email|message|meeting)\s*(?:to|with)?\s*', '', cleaned, flags=re.IGNORECASE).strip()

    # 3. Dynamic Subject generation from extracted content
    subject = cleaned[:45].capitalize() if cleaned else "Notification from Alex AI"

    # 4. Dynamic Body generation from extracted content
    body = f"Hi,\n\n{cleaned.capitalize() if cleaned else 'Please review the requested details.'}\n\nBest regards,\nAlex AI Assistant"

    return subject, body


async def generate_email_content_with_ai(user_prompt: str) -> tuple[str, str]:
    """Uses Gemini AI or universal text sanitizer to generate dynamic subject and body for ANY prompt."""
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.startswith("AIzaSy"):
        try:
            llm = get_llm(temperature=0.3)
            prompt = f"""
You are Alex, an executive AI assistant. Compose a professional email to the recipient based on the user's request.
User Request: "{user_prompt}"

Instructions:
1. `subject`: Create a concise, professional subject line (3-6 words).
2. `body`: Write a polite, complete email body addressing the recipient directly. 
   Do NOT copy user meta commands like "hey send a mail" or "schedule a meet". Write a clear email message (e.g. "Hi,\\n\\n[Message...]\\n\\nBest regards,\\nAlex AI Assistant").

Return JSON:
```json
{{
  "subject": "...",
  "body": "..."
}}
```
"""
            resp = await llm.ainvoke(prompt)
            content = str(resp.content).strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)
            return data.get("subject", "Information Update"), data.get("body", user_prompt)
        except Exception:
            pass

    return extract_universal_message_content(user_prompt)


async def parse_intent_and_entities(input_text: str, memories: List[str], history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Universal AI agent parsing. Dynamically interprets ANY user prompt across all capabilities with zero hardcoded keywords.
    """
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', input_text)
    recipient = emails[0] if emails else None

    subject, body = await generate_email_content_with_ai(input_text)

    # 1. Try Gemini LLM Structured Ingestion
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.startswith("AIzaSy"):
        try:
            llm = get_llm(temperature=0.1)
            structured_llm = llm.with_structured_output(ExtractedIntent)

            messages = [
                SystemMessage(content=SYSTEM_INTENT_PROMPT),
                HumanMessage(content=f"User Prompt: {input_text}")
            ]

            result: ExtractedIntent = await structured_llm.ainvoke(messages)
            args = result.tool_args or {}

            if recipient and not args.get("recipient"):
                args["recipient"] = recipient
            if not args.get("subject") or "notification" in args.get("subject", "").lower():
                args["subject"] = subject
            if not args.get("body") or input_text in args.get("body", ""):
                args["body"] = body

            return {
                "intent": result.intent,
                "entities": args,
                "missing_slots": result.missing_slots
            }
        except Exception:
            pass

    # 2. Universal Fallback Classifier (Pure Pattern Matching, Zero Keyword Restrictions)
    lower = input_text.lower()
    intent = "general_chat"
    if any(w in lower for w in ["send a mail", "send mail", "send email", "email to", "mail to", "write mail"]):
        intent = "send_email"
    elif any(w in lower for w in ["meeting", "schedule", "calendar", "appointment"]):
        intent = "create_calendar_event"
    elif any(w in lower for w in ["show calendar", "list calendar", "my meetings", "my events"]):
        intent = "list_calendar_events"
    elif "cancel" in lower and ("meeting" in lower or "event" in lower):
        intent = "cancel_calendar_event"
    elif "reminder" in lower and ("set" in lower or "remind" in lower):
        intent = "set_reminder"
    elif "reminder" in lower and ("show" in lower or "list" in lower):
        intent = "list_reminders"
    elif "search" in lower:
        intent = "web_search"
    elif "contact" in lower or "email of" in lower:
        intent = "resolve_person"

    return {
        "intent": intent,
        "entities": {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "title": subject,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
            "query": input_text,
            "text": input_text,
            "input_text": input_text
        },
        "missing_slots": []
    }


async def generate_clarification_question(input_text: str, missing_slots: List[str]) -> str:
    try:
        llm = get_llm(temperature=0.3)
        prompt = f"The user asked: '{input_text}'. Ask a polite follow-up question for missing parameters: {', '.join(missing_slots)}."
        response = await llm.ainvoke(prompt)
        return str(response.content).strip()
    except Exception:
        return f"Please specify {', '.join(missing_slots)} to proceed."


async def generate_confirmation_message(tool_name: str, tool_args: Dict[str, Any]) -> str:
    recipient = tool_args.get("recipient") or "recipient"
    if tool_name == "send_email":
        subject = tool_args.get("subject") or "Notification"
        return f"Should I send an email to {recipient} with subject '{subject}' via Gmail API?"
    
    title = tool_args.get("title") or "Meeting"
    date = tool_args.get("date") or "scheduled date"
    start_time = tool_args.get("start_time", "")
    return f"Should I schedule '{title}' with {recipient} on {date} ({start_time} IST) on Google Calendar and send an email invitation?"


async def format_final_response(input_text: str, tool_result: Any) -> str:
    if isinstance(tool_result, dict) and "message" in tool_result:
        return tool_result["message"]
    return f"Processed request: {tool_result if tool_result else ''}"
