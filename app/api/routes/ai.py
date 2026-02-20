"""
AI routes: image scan (Vision) and text chat via LangChain.

- POST /ai/scan-data: upload image, get Vision analysis; if user asks to "make a ticket" / "add a job",
  the Vision model can call a LangChain tool (create_ticket) with extracted data; we execute it and create the ticket.
- POST /ai/chat: send text, get text response (any authenticated user).
"""
import base64
import mimetypes
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pinecone import Pinecone
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.auth import User, get_current_user
from app.core.config import settings
from app.models.approval import Approval
from app.models.event import Event
from app.models.property import Property
from app.models.ticket import Ticket
from app.schemas.approval import ApprovalOut
from app.schemas.ticket import TicketCreate, TicketOut
from app.core.audit import log_audit

router = APIRouter(prefix="/ai", tags=["ai"])


# --- Request/response models for text chat ---
class ChatRequest(BaseModel):
    """Body for POST /ai/chat."""
    message: str = Field(..., min_length=1, max_length=16_000, description="User's text message")


class ChatResponse(BaseModel):
    """Response from POST /ai/chat."""
    reply: str

# --- Constants ---
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_SIZE_MB = 10
DEFAULT_VISION_PROMPT = (
    "Analyze this image in detail. Describe what you see: objects, text, layout, "
    "and any data that might be relevant for a dashboard or report. Be concise but thorough."
)

# --- LangChain tool for creating a ticket from image (Vision can call this) ---
class CreateTicketToolInput(BaseModel):
    """Arguments for the create_ticket tool the Vision model can call."""

    property_id: int = Field(description="Id of the property this ticket belongs to. MUST be one of the property ids from the list provided.")
    type: str = Field(description="Ticket type: one of maintenance, complaint, refund, task.")
    issue: str = Field(description="Full description of the issue: include ALL relevant details from the document (dates, amounts, locations, violation types, due dates, officer names, reference numbers, etc.).")
    priority: str = Field(description="Priority: one of low, medium, high.")
    explanation: str = Field(description="Complete summary of what the ticket is for: include everything from the document (e.g. notice type, fine details, payment due, correction deadline, who signed it).")
    assigned_to: Optional[str] = Field(default=None, description="Optional name of person to assign the ticket to.")
    maintenance_category: Optional[str] = Field(default=None, description="Only for type=maintenance: one of plumbing, hvac, electrical.")
    amount: Optional[float] = Field(default=None, description="If the document contains a fine, payment due, fee, or any monetary amount that requires approval, set this to that amount (number only). An approval will be created for this ticket and property.")
    approval_due_at: Optional[str] = Field(default=None, description="If the document has a payment due date or deadline for the amount, set this to ISO 8601 date-time (e.g. 2024-05-26T23:59:59Z). Only used when amount is set.")
    sla_due_at: Optional[str] = Field(default=None, description="If the document contains a compliance/due date for the ticket, set this to ISO 8601 date-time in UTC (e.g. 2024-05-26T23:59:59Z).")


def _make_create_ticket_tool() -> StructuredTool:
    """Tool schema for the Vision model. When the model calls this, we create the ticket in the route (not here)."""
    def _stub(**kwargs: Any) -> str:
        return "Ticket creation is handled by the backend when the tool is invoked."
    return StructuredTool.from_function(
        func=_stub,
        name="create_ticket",
        description=(
            "Call this to create a maintenance or other ticket from the image. "
            "Use ONLY a property_id from the list of properties provided. "
            "Put ALL relevant details from the document into issue and explanation (dates, amounts, violations, due dates, officer names, etc.). "
            "If the document contains any amount (fine, payment due, fee), include amount and optionally approval_due_at so an approval will be created for the ticket and property. "
            "If the document contains a compliance/due date, include sla_due_at in UTC ISO format. "
            "If the image does not match any of the listed properties, do NOT call this tool."
        ),
        args_schema=CreateTicketToolInput,
    )


# System prompt: AI acts as assistant for the property dashboard
CHAT_SYSTEM_PROMPT = """You are a helpful AI assistant for an internal property management dashboard. You help staff with:

- Questions about properties, units, leases, and occupancy
- Understanding reports (approvals, tickets, events, analytics)
- Summarizing or explaining dashboard data and metrics
- Suggesting next steps (e.g. follow up on pending approvals, prioritize tickets)
- General property-management and workflow questions

Keep answers concise and relevant to the dashboard context. If the user asks something outside property/dashboard scope, briefly answer then steer back to how you can help with the dashboard when relevant."""

MAX_CONTEXT_CHARS = 6000
INTENT_SYSTEM_PROMPT = """Classify the user's intent into one of:
- doc_question: the user is asking a question that should be answered using uploaded documents in Pinecone (policies, invoices, notices, contracts, letters, forms, etc.)
- general: anything else (general chat, dashboard usage, small talk, etc.)
Return only the intent label."""
DOC_QA_SYSTEM_PROMPT = """Answer the user's question using ONLY the provided document context.
If the answer is not in the context, say you don't have enough information from the uploaded documents."""


class IntentResult(BaseModel):
    intent: str = Field(description="One of: doc_question, general")


def _get_pinecone_index() -> Optional[Any]:
    if not settings.PINECONE_API_KEY or not settings.PINECONE_INDEX_NAME:
        return None
    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    return pc.Index(settings.PINECONE_INDEX_NAME)


def _retrieve_context(query: str, top_k: int = 5) -> List[str]:
    index = _get_pinecone_index()
    if index is None or not settings.OPENAI_API_KEY:
        return []

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=settings.OPENAI_API_KEY,
        dimensions=settings.PINECONE_EMBEDDING_DIM,
    )
    vector = embeddings.embed_query(query)
    namespace = settings.PINECONE_NAMESPACE or "documents"
    results = index.query(
        vector=vector,
        top_k=top_k,
        include_metadata=True,
        namespace=namespace,
    )
    matches = getattr(results, "matches", []) or []
    chunks: List[str] = []
    for m in matches:
        meta = getattr(m, "metadata", None) or {}
        text = meta.get("text")
        if text:
            chunks.append(str(text))
    return chunks


def _detect_intent(user_message: str) -> str:
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=settings.OPENAI_API_KEY,
        max_tokens=128,
    )
    response = llm.invoke([
        SystemMessage(content=INTENT_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    intent = (response.content or "").strip().lower()
    if intent not in ("doc_question", "general"):
        return "general"
    return intent


def _answer_general(user_message: str) -> str:
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=settings.OPENAI_API_KEY,
        max_tokens=1024,
    )
    response = llm.invoke([
        SystemMessage(content=CHAT_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    return response.content if hasattr(response, "content") else str(response)


def _answer_with_docs(user_message: str) -> str:
    retrieved: List[str] = []
    try:
        retrieved = _retrieve_context(user_message, top_k=5)
    except Exception:
        retrieved = []

    context_block = ""
    if retrieved:
        joined = "\n\n---\n\n".join(retrieved)
        context_block = joined[:MAX_CONTEXT_CHARS]

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=settings.OPENAI_API_KEY,
        max_tokens=1024,
    )
    response = llm.invoke([
        SystemMessage(content=DOC_QA_SYSTEM_PROMPT),
        HumanMessage(content=f"Document context:\n{context_block}\n\nUser question:\n{user_message}"),
    ])
    return response.content if hasattr(response, "content") else str(response)


def _chat_via_langgraph(user_message: str) -> str:
    def detect_intent(state: dict) -> dict:
        state["intent"] = _detect_intent(state["user_message"])
        return state

    def route(state: dict) -> str:
        return "doc" if state.get("intent") == "doc_question" else "general"

    def answer_doc(state: dict) -> dict:
        state["reply"] = _answer_with_docs(state["user_message"])
        return state

    def answer_general(state: dict) -> dict:
        state["reply"] = _answer_general(state["user_message"])
        return state

    graph = StateGraph(dict)
    graph.add_node("detect_intent", detect_intent)
    graph.add_node("doc", answer_doc)
    graph.add_node("general", answer_general)
    graph.set_entry_point("detect_intent")
    graph.add_conditional_edges("detect_intent", route, {"doc": "doc", "general": "general"})
    graph.add_edge("doc", END)
    graph.add_edge("general", END)
    app = graph.compile()
    result = app.invoke({"user_message": user_message})
    return result.get("reply", "")


def _build_vision_prompt_with_properties(properties_list: List[dict], user_prompt: str) -> str:
    """Build the text prompt for Vision: list of properties + user instruction + when to call create_ticket."""
    if not properties_list:
        return (
            "There are no properties in the system. Do NOT call create_ticket. "
            "Describe the image and say the ticket cannot be created because there are no properties."
        )
    lines = [
        "Properties in the system. When creating a ticket you MUST use one of these property ids:",
        *[f"  - id={p['id']}, name={p['name']}, address={p['address']}" for p in properties_list],
        "",
        f"User instruction or prompt: {user_prompt}",
        "",
        "If the user wants to create a ticket from this image (e.g. 'make a ticket', 'add a job', 'create a ticket'), "
        "call the create_ticket tool. Put ALL relevant details from the document into issue and explanation: dates, amounts, "
        "locations, violation types, due dates, officer names, reference numbers, fine details, payment due, etc. "
        "If the document contains any amount (fine, payment due, fee), set amount to that number and optionally approval_due_at "
        "to the payment/deadline date in ISO format so an approval will be created for the ticket and property. "
        "If the user provides a due date in their instruction, use that for sla_due_at (override document dates). "
        "Otherwise, if the document contains a compliance/due date for the issue, set sla_due_at in UTC ISO format. "
        "Choose the property_id using the image OR the user's instruction (they may provide an address like '1200 Monroe St'). "
        "If the image or user instruction does not match any property, do NOT call the tool.",
    ]
    return "\n".join(lines)


def _analyze_image_with_tools(
    image_base64: str,
    image_mime: str,
    user_prompt: str,
    properties_list: List[dict],
) -> Tuple[str, List[dict]]:
    """
    Run Vision with create_ticket tool bound. Returns (analysis_text, list of create_ticket tool call args).
    When the model decides to create a ticket it will call the tool; we return those args so the route can create the ticket.
    """
    data_url = f"data:{image_mime};base64,{image_base64}"
    prompt = _build_vision_prompt_with_properties(properties_list, user_prompt)

    llm = ChatOpenAI(
        model="gpt-4o",
        api_key=settings.OPENAI_API_KEY,
        max_tokens=1024,
    ).bind_tools([_make_create_ticket_tool()])

    message = HumanMessage(
        content=[
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]
    )

    response = llm.invoke([message])
    analysis_text = (response.content or "").strip() if hasattr(response, "content") else ""

    ticket_calls: List[dict] = []
    for tc in getattr(response, "tool_calls", []) or []:
        if isinstance(tc, dict):
            name = tc.get("name")
            args = tc.get("args") or {}
        else:
            name = getattr(tc, "name", None)
            args = getattr(tc, "args", None) or {}
        if name == "create_ticket" and args:
            ticket_calls.append(args)

    return (analysis_text, ticket_calls)


@router.post("/scan-data")
async def scan_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    image: UploadFile = File(..., description="Image file to analyze (JPEG, PNG, GIF, WebP)"),
    prompt: Optional[str] = Form(None, description="Optional instruction (e.g. 'Make a ticket for it', 'Add a job')"),
):
    """
    Upload an image for analysis. If the user asks to create a ticket ("make a ticket", "add a job"),
    the AI can create one from the image using the list of properties; otherwise returns analysis only.
    - **Authenticated users**: any logged-in user can call this.
    """


    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key is not configured. Set OPENAI_API_KEY in .env.",
        )

    # Validate file type
    content_type = image.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {content_type}. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    # Read and size-check
    data = await image.read()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large: {size_mb:.1f} MB. Max size: {MAX_IMAGE_SIZE_MB} MB.",
        )

    image_mime = content_type
    if not image_mime and image.filename:
        image_mime = mimetypes.guess_type(image.filename)[0] or "image/jpeg"

    image_base64 = base64.standard_b64encode(data).decode("utf-8")
    user_prompt = (prompt or "").strip() or DEFAULT_VISION_PROMPT

    # Fetch all properties so the AI only uses valid property_id values
    properties = db.query(Property).order_by(Property.id).all()
    properties_list = [
        {"id": p.id, "name": p.name, "address": p.address or ""}
        for p in properties
    ]

    try:
        analysis_text, ticket_calls = _analyze_image_with_tools(
            image_base64, image_mime, user_prompt, properties_list
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Vision API error: {str(e)}",
        )

    valid_property_ids: Set[int] = {p["id"] for p in properties_list}

    # If the AI called create_ticket, create the ticket (use first call only)
    if ticket_calls:
        args = ticket_calls[0]
        pid = args.get("property_id")
        try:
            pid = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid = None
        if pid is None or (valid_property_ids and pid not in valid_property_ids):
            return {
                "message": "Data scanned successfully",
                "reply": "Ticket does not belong to any property in the system.",
                "analysis": analysis_text,
                "prompt_used": user_prompt,
                "ticket_created": False,
                "message_from_ai": "Ticket does not belong to any property in the system.",
            }
        # Build TicketCreate from tool args (explanation can be used in issue or as context)
        issue_text = (args.get("issue") or args.get("explanation") or "").strip() or "Issue from image"
        payload_for_create: Any = {
            "property_id": pid,
            "type": str(args.get("type", "maintenance")).strip().lower(),
            "issue": issue_text,
            "priority": str(args.get("priority", "medium")).strip().lower(),
            "assigned_to": args.get("assigned_to") or None,
            "sla_due_at": None,
            "maintenance_category": (args.get("maintenance_category") or "").strip().lower() or None,
        }
        if payload_for_create["type"] not in ("maintenance", "complaint", "refund", "task"):
            payload_for_create["type"] = "maintenance"
        if payload_for_create["priority"] not in ("low", "medium", "high"):
            payload_for_create["priority"] = "medium"
        if payload_for_create["maintenance_category"] == "":
            payload_for_create["maintenance_category"] = None

        raw_sla_due = args.get("sla_due_at")
        if raw_sla_due and isinstance(raw_sla_due, str):
            try:
                sla_dt = datetime.fromisoformat(raw_sla_due.replace("Z", "+00:00"))
                if sla_dt.tzinfo is None:
                    sla_dt = sla_dt.replace(tzinfo=timezone.utc)
                payload_for_create["sla_due_at"] = sla_dt
            except (ValueError, TypeError):
                pass

        try:
            create_schema = TicketCreate(**payload_for_create)
        except Exception as e:
            return {
                "message": "Data scanned successfully",
                "reply": f"Could not create ticket: {str(e)}",
                "analysis": analysis_text,
                "prompt_used": user_prompt,
                "ticket_created": False,
                "message_from_ai": f"Could not create ticket: {str(e)}",
            }
        ticket = Ticket(**create_schema.model_dump())
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        log_audit(
            db,
            actor=current_user,
            action="created",
            entity_type="ticket",
            entity_id=str(ticket.id),
            status=ticket.status,
            due_at=ticket.sla_due_at,
            property_id=pid,
            source="ai",
            description=f"Ticket created from image: {ticket.issue}",
        )

        # If the document contained an amount (fine, payment due), create an approval for this ticket and property
        approval_out = None
        raw_amount = args.get("amount")
        amount_value: Optional[float] = None
        if raw_amount is not None:
            try:
                amount_value = float(raw_amount)
            except (TypeError, ValueError):
                amount_value = None
        if amount_value is not None and amount_value > 0:
            approval_id = f"APR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-T{ticket.id}"
            due_at = None
            raw_due = args.get("approval_due_at")
            if raw_due and isinstance(raw_due, str):
                try:
                    due_at = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            approval = Approval(
                id=approval_id,
                type="vendor_payment",
                amount=Decimal(str(amount_value)),
                ticket_id=ticket.id,
                property_id=pid,
                requested_by=current_user.email or "System",
                due_at=due_at,
            )
            db.add(approval)
            db.commit()
            db.refresh(approval)
            log_audit(
                db,
                actor=current_user,
                action="created",
                entity_type="approval",
                entity_id=str(approval.id),
                status=approval.status,
                due_at=approval.due_at,
                property_id=pid,
                source="ai",
                description=f"Approval created from image: {approval.type} - ${approval.amount}",
            )
            approval_out = ApprovalOut.model_validate(approval)
            event = Event(
                event_type="approval_created",
                property_id=pid,
                approval_id=approval.id,
                description=f"Approval {approval.id} created: {approval.type} - ${approval.amount}",
                due_date=approval.due_at,
            )
            db.add(event)
            db.commit()

        reply_msg = f"Your ticket has been created successfully (Ticket #{ticket.id})."
        if approval_out is not None:
            reply_msg += f" An approval for ${approval_out.amount} has been created for this ticket (Approval {approval_out.id})."

        return {
            "message": "Data scanned successfully",
            "reply": reply_msg,
            "analysis": analysis_text,
            "prompt_used": user_prompt,
            "ticket_created": True,
            "ticket": TicketOut.model_validate(ticket),
            "approval": approval_out,
        }

    return {
        "message": "Data scanned successfully",
        "reply": analysis_text or "Image analyzed. No ticket was requested or created.",
        "analysis": analysis_text,
        "prompt_used": user_prompt,
        "ticket_created": False,
        "message_from_ai": None,
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Send text to the AI and get a text response.

    - **Authenticated users**: any logged-in user can call this.
    - **Body**: `{ "message": "your text here" }` (required, 1–16000 chars).
    - **Returns**: `{ "reply": "AI response text" }`.
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key is not configured. Set OPENAI_API_KEY in .env.",
        )

    try:
        reply = _chat_via_langgraph(body.message)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Chat API error: {str(e)}",
        )

    return ChatResponse(reply=reply)
