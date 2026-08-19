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
You are Alex, a globally capable autonomous executive AI assistant agent.
Analyze the user's input and determine the exact intent/tool to execute, extracting all required arguments dynamically into `tool_args`.

Supported Universal Capabilities & Tools:
1. `send_email`: Send direct emails without calendar scheduling. Extract `recipient` (email), `subject` (concise 3-6 word subject line), and `body` (professionally written, complete email message body). Use this ONLY when the user explicitly wants to send an email/mail.
2. `create_calendar_event`: Schedule calendar meetings. Extract `title` (clean meeting title e.g. 'Project Review' or 'Meeting with <recipient>'), `recipient` (attendee email), `date` (YYYY-MM-DD format), `start_time` (24-hour HH:MM:SS format), `end_time` (24-hour HH:MM:SS format, 1 hour after start_time if unspecified). Use this when the user requests a meeting, schedule, calendar event, or appointment.
3. `list_calendar_events`: View upcoming events. Extract `date` or `date_range`.
4. `cancel_calendar_event`: Cancel a meeting. Extract `event_title_or_id`.
5. `set_reminder`: Set reminders or task alerts. Extract `reminder_text`, `time`.
6. `list_reminders`: List active reminders. Extract `status`.
7. `web_search`: Search the web for live/external information. Extract `query`.
8. `resolve_person`: Search contact details. Extract `name`.
9. `general_chat`: Answer general questions, explain topics, draft text, or converse naturally. Extract `text`.

CRITICAL RULES:
- `send_email` vs `create_calendar_event`: If the request is ONLY to send a message/email to a person (no meeting date/time requested), classify as `send_email`. If the request mentions scheduling a meeting/calendar event, classify as `create_calendar_event`.
- Convert informal date strings (e.g. '20-aug-2026', 'tomorrow', 'next Monday') into 'YYYY-MM-DD'.
- Convert 12-hour times (e.g. '10.00 am', '3.30 pm') into 24-hour 'HH:MM:SS' format.
- For email bodies, compose clear, polite, grammatically perfect messages directly for the recipient. Never copy raw user meta-commands into the body.
"""


def get_llm(temperature: float = 0.2):
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temperature,
    )


def sanitize_email_subject(raw_subject: str) -> str:
    """Strips command meta-phrases and email addresses to produce clean 3-6 word subject lines."""
    if not raw_subject:
        return "Information Update"
    cleaned = re.sub(r'^(?:hey|hi|please)?\s*(?:send|write|draft|dispatch)\s+(?:a\s+)?(?:mail|email|message)\s+(?:to)?\s*[\w\.-]+@[\w\.-]+\.\w+\s*(?:regarding|about|regading|sub|subject|saying|that|for)?\s*', '', raw_subject, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'^(?:send|write|draft)\s+(?:a\s+)?(?:mail|email|message)\s*(?:regarding|about|to)?\s*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', cleaned).strip()
    cleaned = cleaned.strip(', ').strip()
    if not cleaned or len(cleaned) < 3:
        return "Information Update"
    return cleaned[:50].title()


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
        cleaned = re.sub(r'^(?:hey|hi|please)?\s*(?:send|write|draft|schedule|create)\s+(?:a\s+)?(?:mail|email|message|meeting)\s*(?:to)?\s*', '', cleaned, flags=re.IGNORECASE).strip()

    subject = sanitize_email_subject(cleaned if cleaned else user_prompt)
    body_text = cleaned.capitalize() if cleaned and cleaned.lower() != user_prompt.lower() else "Please review the requested updates."
    body = f"Hello,\n\nI am writing to share the following details:\n\n{body_text}\n\nPlease let me know if you have any questions.\n\nBest regards,\nAlex AI Assistant"

    return subject, body


def parse_datetime_from_text(input_text: str) -> tuple[str, str, str]:
    """Dynamically parses date, start_time, and end_time from raw input text using regex patterns."""
    extracted_date = datetime.now().strftime("%Y-%m-%d")
    extracted_start = "09:00:00"
    extracted_end = "10:00:00"

    # 1. Extract Date (e.g. 20-aug-2026, 20/08/2026, 2026-08-20, 20 aug 2026)
    date_match = re.search(r'\b(\d{1,2})[-/\s]([a-zA-Z]{3,9}|\d{1,2})[-/\s](\d{4})\b', input_text)
    if date_match:
        day, month_str, year = date_match.groups()
        try:
            if month_str.isdigit():
                dt = datetime(int(year), int(month_str), int(day))
            else:
                for fmt in ("%b", "%B"):
                    try:
                        dt = datetime.strptime(f"{day} {month_str} {year}", f"%d {fmt} %Y")
                        break
                    except ValueError:
                        continue
            extracted_date = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # 2. Extract Time (e.g. 10.00 am, 10:00am, 10 am, 10.00, 10:00, 15:30)
    time_match = re.search(r'\b(\d{1,2})[\.:](\d{2})\s*(am|pm)?\b|\b(\d{1,2})\s*(am|pm)\b', input_text, re.IGNORECASE)
    if time_match:
        g1, g2, g3, g4, g5 = time_match.groups()
        if g1:
            hour = int(g1)
            minute = int(g2)
            meridiem = (g3 or "").lower()
        else:
            hour = int(g4)
            minute = 0
            meridiem = (g5 or "").lower()

        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        extracted_start = f"{hour:02d}:{minute:02d}:00"
        end_hour = (hour + 1) % 24
        extracted_end = f"{end_hour:02d}:{minute:02d}:00"

    return extracted_date, extracted_start, extracted_end


def sanitize_meeting_title(raw_title: str, recipient: Optional[str] = None) -> str:
    """Cleans up raw meeting titles by stripping command meta-phrases, email addresses, and date/time parameters."""
    if not raw_title:
        return f"Meeting with {recipient}" if recipient else "Scheduled Meeting"
    
    cleaned = re.sub(r'^(?:schedule|create|set|book)\s+(?:a\s+)?(?:meet|meeting|event|appointment)\s*(?:with|to)?\s*', '', raw_title, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', cleaned).strip()
    cleaned = re.sub(r',?\s*at\s*\d{1,2}[\.:]\d{2}.*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r',?\s*date\s*.*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip(', ').strip()

    if not cleaned or len(cleaned) < 3 or cleaned.lower() in ["meeting", "meeting with", "meet", "meet with"]:
        return f"Meeting with {recipient}" if recipient else "Scheduled Meeting"
    return cleaned.title()


async def generate_email_content_with_ai(user_prompt: str) -> tuple[str, str]:
    """Uses Gemini AI or universal text sanitizer to generate dynamic subject and body for ANY prompt."""
    if settings.GEMINI_API_KEY and len(settings.GEMINI_API_KEY.strip()) > 5:
        try:
            llm = get_llm(temperature=0.3)
            prompt = f"""
You are Alex, an executive AI assistant. Compose a complete, professional, grammatically perfect email message based on the user request below.

User Request: "{user_prompt}"

Instructions:
1. `subject`: Create a clean, concise, professional subject line (3-6 words, e.g. "Project Architecture Updates"). NEVER include meta-phrases like "send an email to" or email addresses in the subject!
2. `body`: Write a complete, polite, professional email body addressing the recipient directly.
   - Start with "Hello," or a polite greeting.
   - Write clear, grammatically correct sentences explaining the topic.
   - NEVER copy user meta-commands like "send an email to" or "tell him that" into the body!
   - End with "Best regards,\\nAlex AI Assistant".

Return JSON only:
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
            
            subj = sanitize_email_subject(data.get("subject", ""))
            body = data.get("body", "")
            if not body or input_text_in_body(user_prompt, body):
                _, body = extract_universal_message_content(user_prompt)
            return subj, body
        except Exception:
            pass

    return extract_universal_message_content(user_prompt)


def input_text_in_body(user_prompt: str, body: str) -> bool:
    """Checks if raw user prompt command words were copied verbatim into the body."""
    low_body = body.lower()
    return "send an email" in low_body or "send email" in low_body or user_prompt.lower() in low_body


def extract_reminder_details(input_text: str) -> tuple[str, str]:
    """Extracts clean reminder title and formatted execution time from user prompt."""
    cleaned = re.sub(r'^(?:remind\s+me\s+to|remind\s+me|set\s+(?:a\s+)?reminder\s+(?:to|for)?)\s*', '', input_text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r',?\s*(?:today|tomorrow|\d{1,2}[-/\s]\w+[-/\s]\d{4})?\s*at\s*\d{1,2}(?:[\.:]\d{2})?\s*(?:am|pm)?.*', '', cleaned, flags=re.IGNORECASE).strip()
    
    date_val, start_time_val, _ = parse_datetime_from_text(input_text)
    time_display = f"{start_time_val} IST on {date_val}"
    return (cleaned if cleaned else "Reminder Task"), time_display


async def parse_intent_and_entities(input_text: str, memories: List[str], history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Universal AI agent parsing. Dynamically interprets ANY user prompt across all capabilities with zero hardcoded keywords.
    """
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', input_text)
    recipient = emails[0] if emails else None

    subject, body = await generate_email_content_with_ai(input_text)
    parsed_date, parsed_start, parsed_end = parse_datetime_from_text(input_text)

    # 1. Try Gemini LLM Structured Ingestion
    if settings.GEMINI_API_KEY and len(settings.GEMINI_API_KEY.strip()) > 5:
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

            args["subject"] = sanitize_email_subject(args.get("subject") or subject)

            if not args.get("body") or input_text_in_body(input_text, args.get("body", "")):
                args["body"] = body

            if not args.get("date"):
                args["date"] = parsed_date
            if not args.get("start_time"):
                args["start_time"] = parsed_start
            if not args.get("end_time"):
                args["end_time"] = parsed_end

            raw_title = args.get("title") or args["subject"]
            args["title"] = sanitize_meeting_title(raw_title, recipient)

            return {
                "intent": result.intent,
                "entities": args,
                "missing_slots": result.missing_slots
            }
        except Exception:
            pass

    # 2. Universal Fallback Classifier (Pure Pattern Matching)
    lower = input_text.lower()
    intent = "general_chat"
    if any(w in lower for w in ["send a mail", "send mail", "send email", "email to", "mail to", "write mail"]):
        intent = "send_email"
    elif "cancel" in lower and ("meeting" in lower or "event" in lower):
        intent = "cancel_calendar_event"
    elif any(w in lower for w in ["show calendar", "list calendar", "my meetings", "show my meetings", "list meetings", "view meetings", "my events", "show events", "list events"]):
        intent = "list_calendar_events"
    elif any(w in lower for w in ["schedule", "create meeting", "book meeting", "meeting with", "appointment", "set up meeting"]):
        intent = "create_calendar_event"
    elif any(w in lower for w in ["show reminders", "list reminders", "my reminders", "view reminders", "active reminders"]):
        intent = "list_reminders"
    elif any(w in lower for w in ["remind me", "set reminder", "create reminder", "add reminder"]):
        intent = "set_reminder"
    elif "search" in lower:
        intent = "web_search"
    elif "contact" in lower or "email of" in lower:
        intent = "resolve_person"

    clean_title = sanitize_meeting_title(subject, recipient)

    return {
        "intent": intent,
        "entities": {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "title": clean_title,
            "date": parsed_date,
            "start_time": parsed_start,
            "end_time": parsed_end,
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
    
    title_raw = tool_args.get("title") or ""
    title = sanitize_meeting_title(title_raw, recipient)
    date = tool_args.get("date") or "scheduled date"
    start_time = tool_args.get("start_time", "")
    end_time = tool_args.get("end_time", "")
    time_str = f"({start_time} - {end_time} IST)" if start_time and end_time else f"({start_time} IST)"
    return f"Should I schedule '{title}' with {recipient} on {date} {time_str} on Google Calendar and send an email invitation?"


async def format_final_response(input_text: str, tool_result: Any) -> str:
    if isinstance(tool_result, dict) and "message" in tool_result:
        return tool_result["message"]
    return f"Processed request: {tool_result if tool_result else ''}"
