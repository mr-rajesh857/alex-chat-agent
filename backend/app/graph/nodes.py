import json
from typing import Dict, Any
from app.graph.state import AgentState
from app.llm.client import (
    parse_intent_and_entities,
    generate_clarification_question,
    generate_confirmation_message,
    format_final_response,
)
from app.mcp_client.client import execute_mcp_tool

# Side-effecting tools that require explicit user confirmation
SIDE_EFFECTING_TOOLS = {
    "create_calendar_event",
    "cancel_calendar_event",
    "reschedule_calendar_event",
    "send_email",
    "send_slack_message",
}


async def retrieve_memories_node(state: AgentState) -> Dict[str, Any]:
    """Queries vector database or past sessions for user context."""
    # Placeholder for pgvector memory retrieval
    memories = state.get("retrieved_memories") or []
    return {"retrieved_memories": memories}


async def parse_intent_node(state: AgentState) -> Dict[str, Any]:
    """Uses Gemini to parse user query into intent, entities, and missing slots."""
    input_text = state["input_text"]
    memories = state.get("retrieved_memories", [])
    history = state.get("conversation", [])
    
    parsed = await parse_intent_and_entities(input_text, memories, history)
    if not parsed or not isinstance(parsed, dict):
        parsed = {
            "intent": "general_chat",
            "entities": {"input_text": input_text},
            "missing_slots": []
        }
    
    intent = parsed.get("intent", "general_chat")
    entities = parsed.get("entities", {})
    missing_slots = parsed.get("missing_slots", [])
    
    # Map intent to tool name
    tool_name = None
    if intent in SIDE_EFFECTING_TOOLS or intent in {
        "find_free_slot", "list_calendar_events", "set_reminder", 
        "list_reminders", "resolve_person", "web_search", "get_preferences"
    }:
        tool_name = intent

    return {
        "intent": intent,
        "entities": entities,
        "missing_slots": missing_slots,
        "tool_name": tool_name,
        "tool_args": entities,
    }


async def ask_clarification_node(state: AgentState) -> Dict[str, Any]:
    """Generates a targeted follow-up question for missing slot parameters."""
    missing_slots = state.get("missing_slots", [])
    input_text = state["input_text"]
    
    question = await generate_clarification_question(input_text, missing_slots)
    
    return {
        "final_response": question,
        "pending_confirmation": False,
    }


async def resolve_entities_node(state: AgentState) -> Dict[str, Any]:
    """Fuzzy resolves contact names or relative time expressions."""
    entities = state.get("entities", {})
    # In full MCP integration, resolve_person is called here
    return {"entities": entities, "tool_args": entities}


async def confirm_action_node(state: AgentState) -> Dict[str, Any]:
    """Hard gate for side-effecting actions. Generates confirmation request."""
    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})
    
    confirmation_msg = await generate_confirmation_message(tool_name, tool_args)
    
    return {
        "requires_confirmation": True,
        "pending_confirmation": True,
        "final_response": confirmation_msg,
    }


async def execute_tool_node(state: AgentState) -> Dict[str, Any]:
    """Executes FastMCP tool and records tool execution result."""
    tool_name = state.get("tool_name")
    tool_args = state.get("tool_args", {})
    
    if not tool_name:
        return {"tool_result": {"status": "skipped"}}
    
    try:
        result = await execute_mcp_tool(tool_name, tool_args)
        return {
            "tool_result": result,
            "pending_confirmation": False,
            "requires_confirmation": False,
        }
    except Exception as e:
        return {
            "error": str(e),
            "tool_result": {"status": "error", "message": str(e)},
        }


async def store_memory_node(state: AgentState) -> Dict[str, Any]:
    """Asynchronously indexes notable user facts into pgvector."""
    return {}


async def handle_error_node(state: AgentState) -> Dict[str, Any]:
    """Graceful error fallback."""
    error = state.get("error", "An unexpected error occurred.")
    return {
        "final_response": f"I ran into an issue while executing your request: {error}"
    }


async def respond_node(state: AgentState) -> Dict[str, Any]:
    """Formats final response for the user."""
    input_text = state["input_text"]
    tool_result = state.get("tool_result")
    
    if state.get("final_response") and not tool_result:
        return {}
    
    response = await format_final_response(input_text, tool_result)
    return {"final_response": response}
