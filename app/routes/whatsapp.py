import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.services.orchestration_service import intelligent_orchestrator
from app.services.baileys_service import send_baileys_message, get_baileys_status, baileys_service
from app.services.firebase_service import save_user_session, get_user_session

logger = logging.getLogger(__name__)
router = APIRouter()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "s3nh@-webhook-2025-XYz")

# =================== MODELOS ===================

class WhatsAppAuthorizationRequest(BaseModel):
    session_id: str = Field(..., description="Unique session ID for WhatsApp")
    phone_number: str = Field(..., description="WhatsApp phone number")
    source: str = Field(default="landing_page", description="Authorization source")
    user_data: Optional[Dict[str, Any]] = Field(default=None, description="User data")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class WhatsAppAuthorizationResponse(BaseModel):
    status: str
    session_id: str
    phone_number: str
    source: str
    message: str
    timestamp: str
    expires_in: Optional[int] = Field(default=3600)
    whatsapp_url: str

# =================== VALIDAÇÃO ===================

def validate_phone_number(phone: str) -> str:
    phone_clean = re.sub(r'[^\d]', '', phone)
    
    if len(phone_clean) == 11:
        phone_clean = f"55{phone_clean}"
    elif len(phone_clean) == 13 and phone_clean.startswith("55"):
        pass
    else:
        raise ValueError(f"Invalid phone number format: {phone}")
    
    if not phone_clean.startswith("55"):
        raise ValueError("Phone number must be Brazilian (+55)")
    
    area_code = phone_clean[2:4]
    number = phone_clean[4:]
    
    if not (11 <= int(area_code) <= 99):
        raise ValueError(f"Invalid Brazilian area code: {area_code}")
    
    if not (8 <= len(number) <= 9):
        raise ValueError(f"Invalid phone number length: {len(number)} digits")
    
    return phone_clean

def validate_session_id(session_id: str) -> str:
    if len(session_id) < 10:
        raise ValueError("Session ID too short")
    
    if len(session_id) == 36:
        uuid.UUID(session_id)
    
    if re.search(r'[<>"\'\\\n\r\t]', session_id):
        raise ValueError("Invalid characters in session ID")
    
    return session_id.strip()

# =================== AUTORIZAÇÃO ===================

def extract_session_from_message(message: str) -> Optional[str]:
    if not message:
        return None
        
    patterns = [
        r'whatsapp_\w+_\w+',
        r'session_[\w-]+',
        r'web_\d+',
        r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            session_id = match.group(0)
            logger.info(f"🔍 Session ID extraído: {session_id}")
            return session_id
            
    return None

async def is_session_authorized(session_id: str) -> Dict[str, Any]:
    try:
        if not session_id:
            return {"authorized": False, "action": "IGNORE_COMPLETELY", "reason": "no_session_id"}
            
        auth_data = await get_user_session(f"whatsapp_auth_session:{session_id}")
        
        if not auth_data:
            return {"authorized": False, "action": "IGNORE_COMPLETELY", "reason": "session_not_authorized"}
        
        expires_at_str = auth_data.get("expires_at", "")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                is_expired = datetime.now(expires_at.tzinfo) > expires_at
                
                if is_expired:
                    return {"authorized": False, "action": "IGNORE_COMPLETELY", "reason": "session_expired"}
            except Exception as date_error:
                logger.warning(f"⚠️ Erro ao verificar expiração: {str(date_error)}")
        
        return {
            "authorized": True,
            "action": "RESPOND",
            "session_id": session_id,
            "source": auth_data.get("source"),
            "user_data": auth_data.get("user_data", {}),
            "authorized_at": auth_data.get("authorized_at"),
            "lead_type": auth_data.get("lead_type", "continuous_chat")
        }
        
    except Exception as e:
        logger.error(f"❌ Erro ao verificar autorização: {str(e)}")
        return {"authorized": False, "action": "IGNORE_COMPLETELY", "reason": "error", "error": str(e)}

async def save_session_authorization(session_id: str, auth_data: Dict[str, Any]):
    try:
        await save_user_session(f"whatsapp_auth_session:{session_id}", auth_data)
        logger.info(f"✅ Autorização salva: {session_id}")
    except Exception as e:
        logger.error(f"❌ Erro ao salvar autorização: {str(e)}")
        raise

# =================== WEBHOOK ===================

@router.get("/whatsapp/webhook")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified")
        return PlainTextResponse(challenge or "")
    
    logger.warning("⚠️ WhatsApp webhook verification failed")
    return PlainTextResponse("Forbidden", status_code=403)

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    try:
        payload = await request.json()
        logger.info(f"📨 WhatsApp webhook: {payload}")

        message_text = payload.get("message", "").strip()
        phone_number = payload.get("from", "")
        message_id = payload.get("messageId", "")
        
        clean_phone = phone_number.replace('@s.whatsapp.net', '').replace('@g.us', '')
        
        if not message_text or not phone_number or not message_id:
            logger.warning("⚠️ Invalid webhook payload")
            return {"status": "error", "message": "Invalid payload", "response": "Erro: mensagem inválida"}

        logger.info(f"🔍 Verificando autorização | phone={clean_phone}")

        session_id = extract_session_from_message(message_text)
        
        if not session_id:
            logger.info(f"❌ IGNORANDO - Nenhum session_id encontrado: {clean_phone}")
            return {
                "status": "ignored",
                "phone_number": clean_phone,
                "message_id": message_id,
                "action": "IGNORE_COMPLETELY",
                "reason": "no_session_id_in_message",
                "response": ""
            }
        
        auth_check = await is_session_authorized(session_id)
        
        if not auth_check["authorized"]:
            reason = auth_check.get("reason", "unknown")
            logger.info(f"❌ IGNORANDO - Session não autorizado: {session_id} - {reason}")
            
            return {
                "status": "ignored",
                "phone_number": clean_phone,
                "session_id": session_id,
                "message_id": message_id,
                "action": "IGNORE_COMPLETELY",
                "reason": reason,
                "response": ""
            }

        source = auth_check.get("source", "unknown")
        user_data = auth_check.get("user_data", {})
        lead_type = auth_check.get("lead_type", "continuous_chat")
        
        logger.info(f"✅ DELEGANDO para orchestrator | session={session_id} | source={source}")

        orchestrator_response = await intelligent_orchestrator.process_message(
            message=message_text,
            session_id=session_id,
            phone_number=clean_phone,
            platform="whatsapp"
        )
        
        ai_response = orchestrator_response.get("response", "")
        response_type = orchestrator_response.get("response_type", "orchestrated")
        
        if not ai_response or not isinstance(ai_response, str) or ai_response.strip() == "":
            ai_response = "Obrigado pela sua mensagem! Nossa equipe entrará em contato em breve."
            logger.warning(f"⚠️ Response vazio, usando fallback")
        
        logger.info(f"✅ Response: '{ai_response[:50]}...'")
        
        return {
            "status": "success",
            "message_id": message_id,
            "session_id": session_id,
            "phone_number": clean_phone,
            "source": source,
            "lead_type": lead_type,
            "authorized": True,
            "response": ai_response,
            "response_type": response_type,
            "current_step": orchestrator_response.get("current_step", ""),
            "message_count": orchestrator_response.get("message_count", 1)
        }

    except Exception as e:
        logger.error(f"❌ WhatsApp webhook error: {str(e)}")
        
        return {
            "status": "error",
            "message": str(e),
            "response_type": "error_message",
            "response": "Desculpe, ocorreu um erro temporário. Tente novamente em alguns minutos.",
            "phone_number": clean_phone if 'clean_phone' in locals() else "",
            "message_id": message_id if 'message_id' in locals() else ""
        }

# =================== GATILHO INICIAL ===================

@router.post("/whatsapp/send-initial-message")
async def send_initial_whatsapp_message(request: dict):
    """
    DEPRECATED: This endpoint was for WhatsApp integration from chat.
    The chat flow is now independent and doesn't redirect to WhatsApp.
    This endpoint is kept for backward compatibility but should not be used.
    """
    try:
        logger.warning("⚠️ DEPRECATED endpoint /whatsapp/send-initial-message called")
        
        return {
            "status": "deprecated",
            "message": "This endpoint is deprecated. Chat flow is now independent and doesn't redirect to WhatsApp.",
            "note": "Use the chat flow directly or the WhatsApp button flow separately."
        }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in deprecated WhatsApp trigger: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =================== AUTORIZAÇÃO ===================

@router.post("/whatsapp/authorize")
async def authorize_whatsapp_session(request: WhatsAppAuthorizationRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"🚀 Autorizando sessão: {request.session_id}")
        
        validated_phone = validate_phone_number(request.phone_number)
        validated_session = validate_session_id(request.session_id)
        
        expires_in = 3600
        authorization_data = {
            "session_id": validated_session,
            "phone_number": validated_phone,
            "source": request.source,
            "authorized": True,
            "authorized_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat(),
            "user_data": request.user_data or {},
            "timestamp": request.timestamp,
            "lead_type": "landing_chat_lead" if request.source == "landing_chat" else "whatsapp_button_lead"
        }
        
        background_tasks.add_task(save_session_authorization, validated_session, authorization_data)
        
        auth_data_for_orchestrator = {
            "session_id": validated_session,
            "phone_number": validated_phone,
            "source": request.source,
            "user_data": request.user_data or {}
        }
        
        background_tasks.add_task(intelligent_orchestrator.handle_whatsapp_authorization, auth_data_for_orchestrator)
        
        source_descriptions = {
            "landing_chat": "Chat da landing page completado",
            "landing_button": "Botão WhatsApp direto da landing",
            "landing_page": "Landing page geral"
        }
        source_msg = source_descriptions.get(request.source, request.source)
        
        logger.info(f"✅ Autorização criada | Session: {validated_session} | Origem: {source_msg}")
        
        return WhatsAppAuthorizationResponse(
            status="authorized",
            session_id=validated_session,
            phone_number=validated_phone,
            source=request.source,
            message=f"Sessão {validated_session} autorizada - {source_msg}",
            timestamp=datetime.utcnow().isoformat(),
            expires_in=expires_in,
            whatsapp_url=f"https://wa.me/{validated_phone}"
        )
        
    except ValueError as e:
        logger.error(f"❌ Erro de validação: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"❌ Erro ao autorizar sessão: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")

# =================== CONSULTAS ===================

@router.get("/whatsapp/check-auth/{session_id}")
async def check_whatsapp_authorization(session_id: str):
    try:
        logger.info(f"📱 Verificando autorização: {session_id}")
        
        auth_check = await is_session_authorized(session_id)
        
        status_msg = "AUTORIZADO" if auth_check["authorized"] else "NÃO AUTORIZADO"
        logger.info(f"{'✅' if auth_check['authorized'] else '❌'} {status_msg}: {session_id}")
        
        return {
            "session_id": session_id,
            **auth_check,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Erro ao verificar sessão: {str(e)}")
        return {
            "session_id": session_id,
            "authorized": False,
            "action": "IGNORE_COMPLETELY",
            "reason": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@router.delete("/whatsapp/revoke-auth/{session_id}")
async def revoke_whatsapp_authorization(session_id: str):
    try:
        validated_session = validate_session_id(session_id)
        await save_user_session(f"whatsapp_auth_session:{validated_session}", None)
        
        logger.info(f"🗑️ Autorização revogada: {validated_session}")
        
        return {
            "session_id": validated_session,
            "status": "revoked",
            "message": "Autorização removida com sucesso",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Erro ao revogar: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro ao revogar autorização")

@router.get("/whatsapp/sessions/{session_id}")
async def get_whatsapp_session_info(session_id: str):
    try:
        logger.info(f"📊 Buscando info da sessão: {session_id}")
        
        session_info = await intelligent_orchestrator.get_session_context(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            "session_info": session_info,
            "platform": "whatsapp",
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ Erro ao buscar sessão {session_id}: {str(e)}")
        return {
            "status": "error",
            "session_id": session_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# =================== BAILEYS ===================

@router.post("/whatsapp/send")
async def send_whatsapp_message(request: dict):
    try:
        phone_number = request.get("phone_number", "")
        message = request.get("message", "")
        
        if not phone_number or not message:
            raise HTTPException(status_code=400, detail="Missing phone_number or message")

        logger.info(f"📤 Envio manual WhatsApp para {phone_number}")
        success = await send_baileys_message(phone_number, message)

        if success:
            logger.info(f"✅ Mensagem enviada para {phone_number}")
            return {"status": "success", "message": "WhatsApp message sent successfully", "to": phone_number}
        
        logger.error(f"❌ Falha ao enviar para {phone_number}")
        raise HTTPException(status_code=500, detail="Failed to send WhatsApp message")

    except Exception as e:
        logger.error(f"❌ Erro ao enviar: {str(e)}")
        raise HTTPException(status_code=500, detail=f"WhatsApp message sending error: {str(e)}")

@router.get("/whatsapp/status")
async def whatsapp_status():
    try:
        status = await get_baileys_status()
        logger.info(f"📊 Status WhatsApp: {status.get('status', 'unknown')}")
        return status
    except Exception as e:
        logger.error(f"❌ Erro ao obter status: {str(e)}")
        return {
            "service": "baileys_whatsapp", 
            "status": "error", 
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }