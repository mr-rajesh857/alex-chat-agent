from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any, Optional
import uuid

from app.db.session import get_db
from app.db.models import User, SessionModel, ConversationTurn, AgentStateCheckpoint
from app.routers.auth import get_current_user
from app.graph.builder import agent_graph
from app.graph.state import AgentState
from app.mcp_client.client import execute_mcp_tool

router = APIRouter(prefix="/chat", tags=["Chat & Agent Orchestrator"])


class ChatMessageRequest(BaseModel):
    session_id: Optional[str] = None
    input_text: str
    confirmation_response: Optional[bool] = None  # True if user clicked Confirm, False if Cancel


class ChatMessageResponse(BaseModel):
    session_id: str
    response_text: str
    intent: Optional[str] = None
    requires_confirmation: bool = False
    pending_confirmation: bool = False
    confirmation_payload: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None


@router.post("/message", response_model=ChatMessageResponse)
async def send_chat_message(
    payload: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 1. Resolve or create chat session
    session_id = payload.session_id
    if not session_id:
        new_session = SessionModel(user_id=current_user.id, title=payload.input_text[:30])
        db.add(new_session)
        await db.commit()
        await db.refresh(new_session)
        session_id = str(new_session.id)
    else:
        try:
            sess_uuid = uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session ID")
            
        stmt = select(SessionModel).where(SessionModel.id == sess_uuid, SessionModel.user_id == current_user.id)
        result = await db.execute(stmt)
        sess = result.scalar_one_or_none()
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")

    # 2. Record User Turn
    user_turn = ConversationTurn(
        session_id=uuid.UUID(session_id),
        role="user",
        content=payload.input_text
    )
    db.add(user_turn)
    await db.commit()

    # 3. Load Checkpointed Graph State or initialize new AgentState
    stmt = select(AgentStateCheckpoint).where(AgentStateCheckpoint.session_id == uuid.UUID(session_id))
    result = await db.execute(stmt)
    checkpoint = result.scalar_one_or_none()

    if checkpoint and isinstance(checkpoint.state_json, dict):
        initial_state = checkpoint.state_json
        initial_state["input_text"] = payload.input_text

        # Check if the previous turn was waiting for user confirmation
        if initial_state.get("pending_confirmation"):
            user_input_lower = payload.input_text.strip().lower()
            
            # Check if this input is a new command rather than a confirmation response
            is_new_command = (
                payload.confirmation_response is None and
                any(kw in user_input_lower for kw in ["schedule", "create", "send", "book", "remind", "list", "show", "cancel", "search", "mail", "email", "meeting"])
            )

            if not is_new_command:
                is_confirmed = (
                    payload.confirmation_response is True or 
                    user_input_lower in ["yes", "yep", "sure", "confirm", "proceed", "yes proceed", "yes confirm"]
                )
                is_cancelled = (
                    payload.confirmation_response is False or
                    user_input_lower in ["no", "cancel", "stop", "reject", "don't send", "do not send"]
                )

                if is_confirmed:
                    tool_name = initial_state.get("tool_name", "create_calendar_event")
                    tool_args = initial_state.get("tool_args", {})
                    
                    tool_res = await execute_mcp_tool(tool_name, tool_args)
                    response_text = tool_res.get("message", "✅ Action executed successfully!")
                    
                    final_state = {
                        **initial_state,
                        "pending_confirmation": False,
                        "requires_confirmation": False,
                        "confirmation_given": True,
                        "tool_result": tool_res,
                        "final_response": response_text
                    }
                elif is_cancelled:
                    response_text = "❌ Action cancelled by user. No changes were made."
                    final_state = {
                        **initial_state,
                        "pending_confirmation": False,
                        "requires_confirmation": False,
                        "confirmation_given": False,
                        "final_response": response_text
                    }
                else:
                    is_new_command = True

            if not is_new_command:
                # Save assistant turn & updated checkpoint
                assistant_turn = ConversationTurn(
                    session_id=uuid.UUID(session_id),
                    role="assistant",
                    content=response_text
                )
                db.add(assistant_turn)
                checkpoint.state_json = final_state
                await db.commit()

                return ChatMessageResponse(
                    session_id=session_id,
                    response_text=response_text,
                    intent=final_state.get("intent"),
                    requires_confirmation=False,
                    pending_confirmation=False,
                    confirmation_payload=None,
                    tool_result=final_state.get("tool_result"),
                )
            db.add(assistant_turn)
            checkpoint.state_json = final_state
            await db.commit()

            return ChatMessageResponse(
                session_id=session_id,
                response_text=response_text,
                intent=final_state.get("intent"),
                requires_confirmation=False,
                pending_confirmation=False,
                confirmation_payload=None,
                tool_result=final_state.get("tool_result"),
            )
    else:
        initial_state: AgentState = {
            "session_id": session_id,
            "user_id": str(current_user.id),
            "user_name": current_user.name,
            "input_text": payload.input_text,
            "conversation": [{"role": "user", "content": payload.input_text}],
            "retrieved_memories": [],
            "intent": None,
            "entities": {},
            "missing_slots": [],
            "requires_confirmation": False,
            "pending_confirmation": False,
            "confirmation_given": payload.confirmation_response,
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "final_response": None,
            "is_interrupted": False,
            "error": None,
        }

    # 4. Invoke LangGraph Orchestrator Graph for new request
    final_state = await agent_graph.ainvoke(initial_state)
    response_text = final_state.get("final_response") or "I processed your request."
    
    # 5. Record Assistant Turn
    assistant_turn = ConversationTurn(
        session_id=uuid.UUID(session_id),
        role="assistant",
        content=response_text
    )
    db.add(assistant_turn)

    # 6. Checkpoint updated graph state
    if checkpoint:
        checkpoint.state_json = final_state
    else:
        new_checkpoint = AgentStateCheckpoint(
            session_id=uuid.UUID(session_id),
            state_json=final_state
        )
        db.add(new_checkpoint)

    await db.commit()

    # Prepare Confirmation Payload for Frontend
    confirmation_payload = None
    if final_state.get("pending_confirmation") and final_state.get("tool_name"):
        confirmation_payload = {
            "tool_name": final_state.get("tool_name"),
            "tool_args": final_state.get("tool_args"),
            "message": response_text
        }

    return ChatMessageResponse(
        session_id=session_id,
        response_text=response_text,
        intent=final_state.get("intent"),
        requires_confirmation=bool(final_state.get("requires_confirmation")),
        pending_confirmation=bool(final_state.get("pending_confirmation")),
        confirmation_payload=confirmation_payload,
        tool_result=final_state.get("tool_result"),
    )


@router.get("/sessions")
async def get_user_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(SessionModel).where(SessionModel.user_id == current_user.id).order_by(SessionModel.started_at.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "title": s.title or "Chat Session",
            "started_at": s.started_at.isoformat() if s.started_at else None
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/turns")
async def get_session_turns(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        sess_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
        
    stmt = select(ConversationTurn).where(ConversationTurn.session_id == sess_uuid).order_by(ConversationTurn.created_at.asc())
    result = await db.execute(stmt)
    turns = result.scalars().all()
    
    return [
        {
            "id": str(t.id),
            "role": t.role,
            "content": t.content,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }
        for t in turns
    ]
