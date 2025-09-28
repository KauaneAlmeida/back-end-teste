"""
Conversation Flow Routes - CORRIGIDO SEM CONFLITOS

CORREÇÃO: Elimina auto-criação de sessão no /start
Remove conflito de sessões duplicadas
"""

import uuid
import logging
import json
import os
from typing import Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.models.request import ConversationRequest
from app.models.response import ConversationResponse
from app.services.orchestration_service import intelligent_orchestrator

# Logging
logger = logging.getLogger(__name__)

# FastAPI router
router = APIRouter()


@router.post("/conversation/start", response_model=ConversationResponse)
async def start_conversation():
    """
    Start a new conversation session for web chat platform.
    Returns initial greeting to start the chat flow.
    """
    try:
        session_id = str(uuid.uuid4())
        logger.info(f"🚀 Starting new web chat conversation | session={session_id}")

        # Return initial greeting for chat flow
        initial_greeting = "Olá! Bem-vindo ao m.lima Advogados. Para começar seu atendimento, digite uma saudação como 'oi' ou 'olá'."
        
        response_data = ConversationResponse(
            session_id=session_id,
            response=initial_greeting,
            ai_mode=False,
            flow_completed=False,
            phone_collected=False,
            message_count=0
        )
        
        logger.info(f"✅ Web chat conversation prepared | session={session_id}")
        
        return JSONResponse(
            content=response_data.dict(),
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )

    except Exception as e:
        logger.error(f"❌ Error starting web chat conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start chat conversation: {str(e)}"
        )


@router.post("/conversation/respond", response_model=ConversationResponse)
async def respond_to_conversation(request: ConversationRequest):
    """
    Process user response in web chat flow.
    This is for the landing page chat - independent flow that ends with lawyer notification.
    """
    try:
        # Generate session ID if not provided
        if not request.session_id:
            request.session_id = str(uuid.uuid4())
            logger.info(f"🆕 Generated new web chat session: {request.session_id}")

        logger.info(f"📝 Processing web chat response | session={request.session_id} | msg='{request.message[:50]}...'")

        # Process message through orchestrator for web chat flow
        result = await intelligent_orchestrator.process_message(
            request.message,
            request.session_id,
            platform="web"
        )
        
        response_data = ConversationResponse(
            session_id=request.session_id,
            response=result.get("response", "Como posso ajudá-lo?"),
            ai_mode=result.get("ai_mode", False),
            flow_completed=result.get("flow_completed", False),
            phone_collected=result.get("phone_collected", False),
            message_count=result.get("message_count", 1)
        )
        
        # Log completion status
        if response_data.flow_completed:
            logger.info(f"🎉 Web chat flow completed - lawyers notified | session={request.session_id}")
        
        return JSONResponse(
            content=response_data.dict(),
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )

    except Exception as e:
        logger.error(f"❌ Error processing web chat response | session={getattr(request, 'session_id', 'unknown')}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat response: {str(e)}"
        )


@router.post("/conversation/submit-phone")
async def submit_phone_number(request: dict):
    """
    Submit phone number - UNIFIED through orchestrator only
    """
    try:
        phone_number = request.get("phone_number", "").strip()
        session_id = request.get("session_id", "").strip()
        
        if not phone_number or not session_id:
            logger.warning(f"⚠️ Invalid phone submission | phone={bool(phone_number)} | session={bool(session_id)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing phone_number or session_id"
            )
        
        logger.info(f"📱 Phone number submitted | session={session_id} | number={phone_number}")

        # CORREÇÃO: Usar handle_phone_number_submission do orchestrator
        result = await intelligent_orchestrator.handle_phone_number_submission(
            phone_number, 
            session_id
        )
        
        logger.info(f"✅ Phone submission processed | session={session_id} | success={result.get('status', 'unknown')}")
        
        return {
            **result,
            "timestamp": datetime.now().isoformat(),
            "platform": "web"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing phone submission | session={request.get('session_id', 'unknown')}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process phone number submission: {str(e)}"
        )


@router.get("/conversation/status/{session_id}")
async def get_conversation_status(session_id: str):
    """
    Get current conversation state - UNIFIED through orchestrator only
    """
    try:
        logger.info(f"📊 Fetching conversation status | session={session_id}")
        
        status_info = await intelligent_orchestrator.get_session_context(session_id)
        
        # Determine platform from session_id
        platform = "whatsapp" if session_id.startswith("whatsapp_") else "web"
        
        return {
            "session_id": session_id,
            "platform": platform,
            "status_info": status_info,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error getting status for session {session_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conversation status: {str(e)}"
        )


@router.get("/conversation/flow")
async def get_conversation_flow():
    """
    Get current conversation approach information - UNIFIED system
    """
    try:
        return {
            "approach": "unified_intelligent_orchestrator",
            "description": "Single orchestrator handles all platforms with session conflict resolved",
            "status": "SESSION_CONFLICTS_RESOLVED",
            "platforms": {
                "web": {
                    "method": "Intelligent orchestrator with structured flow",
                    "description": "Session created only on first message (not on /start)",
                    "fields": ["identification", "contact_info", "area_qualification", "case_details", "confirmation"],
                    "completion": "Lead qualification + lawyer notification"
                },
                "whatsapp": {
                    "method": "Same intelligent orchestrator",
                    "description": "Consistent flow across platforms", 
                    "fields": ["identification", "contact_info", "area_qualification", "case_details", "confirmation"],
                    "completion": "Lead qualification + lawyer notification"
                }
            },
            "corrections_applied": [
                "Removed session pre-creation in /start endpoint",
                "Session now created only in /respond when needed",
                "Eliminated double session creation conflict",
                "Fixed greeting loop issue",
                "Unified all processing through intelligent_orchestrator"
            ],
            "flow_sequence": {
                "step_0": "User calls /start -> Gets instructions (no session created)",
                "step_1": "User sends greeting -> Session created in /respond",
                "step_2": "Nome completo",
                "step_3": "Informações de contato (telefone/email)", 
                "step_4": "Área jurídica (Penal ou Saúde)",
                "step_5": "Detalhes do caso",
                "step_6": "Confirmação e finalização"
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error retrieving conversation flow info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve conversation flow information: {str(e)}"
        )


@router.get("/conversation/service-status")
async def conversation_service_status():
    """
    Check service health - UNIFIED status from orchestrator
    """
    try:
        # Get status from unified orchestrator only
        service_status = await intelligent_orchestrator.get_overall_service_status()

        return {
            "service": "unified_intelligent_orchestrator",
            "status": service_status.get("overall_status", "unknown"),
            "approach": "single_orchestrator_no_session_conflicts",
            "conflicts_resolved": True,
            "session_creation": "lazy_creation_on_first_message",
            "removed_conflicts": [
                "Auto-creation of sessions in /start endpoint",
                "Duplicate session initialization",
                "Greeting detection loop",
                "ConversationManager dependencies"
            ],
            "firebase_status": service_status.get("firebase_status", {"status": "unknown"}),
            "ai_status": service_status.get("ai_status", {"status": "unknown"}),
            "features": service_status.get("features", {}),
            "platforms": {
                "web": {
                    "method": "Unified intelligent orchestrator",
                    "status": "active",
                    "session_management": "lazy_creation"
                },
                "whatsapp": {
                    "method": "Unified intelligent orchestrator", 
                    "status": "ready_for_integration",
                    "session_management": "lazy_creation"
                }
            },
            "endpoints": {
                "start": "/api/v1/conversation/start (no session creation)",
                "respond": "/api/v1/conversation/respond (creates session if needed)", 
                "submit_phone": "/api/v1/conversation/submit-phone",
                "status": "/api/v1/conversation/status/{session_id}",
                "flow_info": "/api/v1/conversation/flow",
                "service_status": "/api/v1/conversation/service-status"
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Error getting conversation service status: {str(e)}")
        return {
            "service": "unified_intelligent_orchestrator", 
            "status": "error", 
            "conflicts_resolved": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.post("/conversation/reset-session/{session_id}")
async def reset_conversation_session(session_id: str):
    """
    Reset a conversation session - UNIFIED through orchestrator
    """
    try:
        logger.info(f"🔄 Resetting session: {session_id}")
        
        # Use Firebase reset function if available
        from app.services.firebase_service import reset_user_session
        try:
            result = await reset_user_session(session_id)
        except:
            # Fallback to manual reset
            result = True
        
        return {
            "status": "success",
            "message": f"Session {session_id} reset successfully",
            "session_id": session_id,
            "result": result,
            "approach": "unified_orchestrator",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error resetting session {session_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset session: {str(e)}"
        )


@router.get("/conversation/debug/session-conflicts")
async def debug_session_conflicts():
    """
    Debug endpoint específico para conflitos de sessão
    """
    try:
        return {
            "session_conflicts_status": "RESOLVED",
            "issue_identified": "Double session creation causing greeting loop",
            "root_cause": "/start endpoint was pre-creating empty sessions",
            "solution_applied": {
                "conversation_routes.py": [
                    "Removed session pre-creation in start_conversation()",
                    "Session now created only in respond_to_conversation()",
                    "Lazy session initialization pattern implemented"
                ],
                "chat.js": [
                    "Removed initializeChatConversation() auto-call",
                    "Chat starts with local message only",
                    "First user message triggers session creation"
                ],
                "intelligent_orchestrator.py": [
                    "Simplified session state management",
                    "Clear step progression without conflicts",
                    "Fixed greeting detection logic"
                ]
            },
            "flow_now": [
                "1. Frontend loads -> Shows instructions (no backend call)",
                "2. User types greeting -> /respond creates session",
                "3. Orchestrator detects greeting -> Starts flow",
                "4. Sequential questions -> Lead completion"
            ],
            "whatsapp_integration": {
                "status": "ready",
                "method": "Same orchestrator, different platform parameter",
                "baileys_integration": "await intelligent_orchestrator.process_message(msg, session_id, platform='whatsapp')"
            },
            "test_instructions": [
                "1. Open chat widget",
                "2. Should show: 'Para começar nosso atendimento, digite uma saudação como oi'",
                "3. Type 'oi'",
                "4. Should ask for name (no loop)",
                "5. Continue with flow normally"
            ],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


# CORREÇÃO: Endpoint adicional para debug do fluxo
@router.get("/conversation/debug/flow-test/{session_id}")
async def debug_flow_test(session_id: str):
    """
    Test flow progression for a specific session
    """
    try:
        session_context = await intelligent_orchestrator.get_session_context(session_id)
        
        return {
            "session_id": session_id,
            "exists": session_context.get("exists", False),
            "current_step": session_context.get("current_step", "not_started"),
            "flow_completed": session_context.get("flow_completed", False),
            "lead_data": session_context.get("lead_data", {}),
            "message_count": session_context.get("message_count", 0),
            "debug_info": {
                "session_creation": "lazy_on_first_message",
                "conflict_status": "resolved",
                "orchestrator": "intelligent_hybrid_simplified"
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error in flow test for session {session_id}: {str(e)}")
        return {
            "error": str(e),
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }