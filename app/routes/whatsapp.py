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
from app.services.baileys_service import (
    send_baileys_message,
    get_baileys_status,
    baileys_service
)
from app.services.firebase_service import save_user_session, get_user_session

# Logging
logger = logging.getLogger(__name__)

# FastAPI router
router = APIRouter()

# Token de verificação para o webhook do WhatsApp
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "s3nh@-webhook-2025-XYz")

# =================== MODELOS DE DADOS ===================

class WhatsAppAuthorizationRequest(BaseModel):
    """Request model for WhatsApp session authorization"""
    session_id: str = Field(..., description="Unique session ID for WhatsApp")
    phone_number: str = Field(..., description="WhatsApp phone number (format: 5511918368812)")
    source: str = Field(default="landing_page", description="Source of authorization (landing_chat, landing_button)")
    user_data: Optional[Dict[str, Any]] = Field(default=None, description="User data from landing page chat")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="Authorization timestamp")
    user_agent: Optional[str] = Field(default=None, description="User agent for tracking")
    page_url: Optional[str] = Field(default=None, description="Page URL where authorization was requested")

class WhatsAppAuthorizationResponse(BaseModel):
    """Response model for WhatsApp authorization"""
    status: str = Field(..., description="Authorization status (authorized, error)")
    session_id: str = Field(..., description="Session ID that was authorized")
    phone_number: str = Field(..., description="Phone number for the session")
    source: str = Field(..., description="Authorization source")
    message: str = Field(..., description="Status message")
    timestamp: str = Field(..., description="Authorization timestamp")
    expires_in: Optional[int] = Field(default=3600, description="Authorization expiry in seconds")
    whatsapp_url: str = Field(..., description="WhatsApp deep link URL")

# =================== FUNÇÕES DE VALIDAÇÃO ===================

def validate_phone_number(phone: str) -> str:
    """
    Validate and normalize Brazilian phone number
    """
    try:
        # Remove any non-digit characters
        phone_clean = re.sub(r'[^\d]', '', phone)
        
        # Validate length (should be 13 digits with country code, or 11 without)
        if len(phone_clean) == 11:
            # Add Brazil country code
            phone_clean = f"55{phone_clean}"
        elif len(phone_clean) == 13 and phone_clean.startswith("55"):
            # Already has country code
            pass
        else:
            raise ValueError(f"Invalid phone number format: {phone}")
        
        # Validate Brazilian format
        if not phone_clean.startswith("55"):
            raise ValueError("Phone number must be Brazilian (+55)")
        
        # Extract area code and number
        area_code = phone_clean[2:4]
        number = phone_clean[4:]
        
        # Validate area code (11-99)
        if not (11 <= int(area_code) <= 99):
            raise ValueError(f"Invalid Brazilian area code: {area_code}")
        
        # Validate number length (8-9 digits)
        if not (8 <= len(number) <= 9):
            raise ValueError(f"Invalid phone number length: {len(number)} digits")
        
        return phone_clean
        
    except Exception as e:
        logger.error(f"❌ Phone validation error: {str(e)}")
        raise ValueError(f"Invalid phone number: {phone}")

def validate_session_id(session_id: str) -> str:
    """
    Validate session ID format and security
    """
    try:
        # Check if it's a valid UUID format or custom format
        if len(session_id) < 10:
            raise ValueError("Session ID too short")
        
        # Allow UUID or custom format
        if len(session_id) == 36:
            uuid.UUID(session_id)  # Validates UUID format
        
        # Check for dangerous characters
        if re.search(r'[<>"\'\\\n\r\t]', session_id):
            raise ValueError("Invalid characters in session ID")
        
        return session_id.strip()
        
    except Exception as e:
        logger.error(f"❌ Session ID validation error: {str(e)}")
        raise ValueError(f"Invalid session ID: {session_id}")

# =================== FUNÇÕES DE AUTORIZAÇÃO POR SESSION_ID ===================

def extract_session_from_message(message: str) -> Optional[str]:
    """
    Extrai session_id da mensagem do usuário.
    Procura por padrões como: whatsapp_1234567890_abc123, session_abc123, etc.
    """
    try:
        if not message:
            return None
            
        # Padrões de session_id que podem aparecer na mensagem
        patterns = [
            r'whatsapp_\w+_\w+',  # whatsapp_1234567890_abc123
            r'session_[\w-]+',     # session_abc123
            r'web_\d+',           # web_1234567890
            r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',  # UUID format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                session_id = match.group(0)
                logger.info(f"🔍 Session ID extraído da mensagem: {session_id}")
                return session_id
                
        return None
        
    except Exception as e:
        logger.error(f"❌ Erro ao extrair session_id: {str(e)}")
        return None

async def is_session_authorized(session_id: str) -> Dict[str, Any]:
    """
    Verifica se um session_id está autorizado para usar WhatsApp.
    """
    try:
        if not session_id:
            return {
                "authorized": False,
                "action": "IGNORE_COMPLETELY",
                "reason": "no_session_id"
            }
            
        # Buscar autorização no Firebase usando session_id
        auth_data = await get_user_session(f"whatsapp_auth_session:{session_id}")
        
        if not auth_data:
            return {
                "authorized": False,
                "action": "IGNORE_COMPLETELY", 
                "reason": "session_not_authorized"
            }
        
        # Verificar expiração
        expires_at_str = auth_data.get("expires_at", "")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                is_expired = datetime.now(expires_at.tzinfo) > expires_at
                
                if is_expired:
                    return {
                        "authorized": False,
                        "action": "IGNORE_COMPLETELY",
                        "reason": "session_expired"
                    }
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
        logger.error(f"❌ Erro ao verificar autorização da sessão: {str(e)}")
        return {
            "authorized": False,
            "action": "IGNORE_COMPLETELY",
            "reason": "error",
            "error": str(e)
        }

async def save_session_authorization(session_id: str, auth_data: Dict[str, Any]):
    """
    Salva autorização de sessão no Firebase.
    """
    try:
        await save_user_session(f"whatsapp_auth_session:{session_id}", auth_data)
        logger.info(f"✅ Autorização de sessão salva: {session_id}")
    except Exception as e:
        logger.error(f"❌ Erro ao salvar autorização de sessão: {str(e)}")
        raise

# =================== FUNÇÕES DE AUTORIZAÇÃO ===================

# Manter função legada para compatibilidade (DEPRECIADA)
async def is_phone_authorized(phone_number: str) -> Dict[str, Any]:
    """DEPRECIADA: Use is_session_authorized() em vez desta função"""
    logger.warning("⚠️ is_phone_authorized() está DEPRECIADA - use is_session_authorized()")
    return {
        "authorized": False,
        "action": "IGNORE_COMPLETELY",
        "reason": "deprecated_phone_auth"
    }

# =================== WEBHOOK PRINCIPAL ===================

@router.get("/whatsapp/webhook")
async def verify_whatsapp_webhook(request: Request):
    """
    Handler GET para a Meta verificar o webhook do WhatsApp.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully")
        return PlainTextResponse(challenge or "")
    
    logger.warning("⚠️ WhatsApp webhook verification failed")
    return PlainTextResponse("Forbidden", status_code=403)

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """
    🔧 WEBHOOK CORRIGIDO - AUTORIZAÇÃO POR SESSION_ID
    """
    try:
        payload = await request.json()
        logger.info(f"📨 WhatsApp webhook received: {payload}")

        # Extract message details
        message_text = payload.get("message", "").strip()
        phone_number = payload.get("from", "")
        message_id = payload.get("messageId", "")
        
        # Clean phone number for validation
        clean_phone = phone_number.replace('@s.whatsapp.net', '').replace('@g.us', '')
        
        # Validation
        if not message_text or not phone_number or not message_id:
            logger.warning("⚠️ Invalid webhook payload - missing required fields")
            return {
                "status": "error", 
                "message": "Invalid payload",
                "response": "Erro: mensagem inválida"  # ✅ SEMPRE TEM RESPONSE
            }

        logger.info(f"🔍 Verificando autorização por session_id | phone={clean_phone} | msg='{message_text[:50]}...'")

        # 🔧 NOVA LÓGICA: EXTRAIR SESSION_ID DA MENSAGEM
        session_id = extract_session_from_message(message_text)
        
        if not session_id:
            logger.info(f"❌ IGNORANDO mensagem de {clean_phone} - Nenhum session_id encontrado na mensagem")
            return {
                "status": "ignored",
                "phone_number": clean_phone,
                "message_id": message_id,
                "action": "IGNORE_COMPLETELY",
                "reason": "no_session_id_in_message",
                "response": ""
            }
        
        # VERIFICAÇÃO DE AUTORIZAÇÃO POR SESSION_ID
        auth_check = await is_session_authorized(session_id)
        
        if not auth_check["authorized"]:
            reason = auth_check.get("reason", "unknown")
            logger.info(f"❌ IGNORANDO mensagem de {clean_phone} - Session: {session_id} - Razão: {reason}")
            
            return {
                "status": "ignored",
                "phone_number": clean_phone,
                "session_id": session_id,
                "message_id": message_id,
                "action": "IGNORE_COMPLETELY",
                "reason": reason,
                "response": ""
            }

        # ✅ SESSION_ID AUTORIZADO - DELEGAR TUDO PARA ORCHESTRATOR
        source = auth_check.get("source", "unknown")
        user_data = auth_check.get("user_data", {})
        lead_type = auth_check.get("lead_type", "continuous_chat")
        
        logger.info(f"✅ DELEGANDO para orchestrator | session={session_id} | source={source} | type={lead_type}")

        # DELEGAR PARA ORCHESTRATION SERVICE
        orchestrator_response = await intelligent_orchestrator.process_message(
            message=message_text,
            session_id=session_id,
            phone_number=clean_phone,
            platform="whatsapp"
        )
        
        # EXTRAIR RESPONSE DO ORCHESTRATOR COM VALIDAÇÃO
        ai_response = orchestrator_response.get("response", "")
        response_type = orchestrator_response.get("response_type", "orchestrated")
        
        # GARANTIR QUE RESPONSE NUNCA ESTÁ VAZIO
        if not ai_response or not isinstance(ai_response, str) or ai_response.strip() == "":
            ai_response = "Obrigado pela sua mensagem! Nossa equipe entrará em contato em breve."
            logger.warning(f"⚠️ Orchestrator response vazio ou inválido, usando fallback: {ai_response}")
        
        logger.info(f"✅ Response para bot WhatsApp: '{ai_response[:50]}...'")
        
        # RESPOSTA FINAL COM CAMPO 'response' GARANTIDO
        final_response = {
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
        
        logger.info(f"✅ FINAL RESPONSE enviado para bot: response='{ai_response[:30]}...', status={final_response['status']}")
        
        return final_response

    except Exception as e:
        logger.error(f"❌ WhatsApp webhook error: {str(e)}")
        
        # MESMO EM ERRO, SEMPRE RETORNA RESPONSE
        return {
            "status": "error",
            "message": str(e),
            "response_type": "error_message",
            "response": "Desculpe, ocorreu um erro temporário. Tente novamente em alguns minutos.",
            "phone_number": clean_phone if 'clean_phone' in locals() else "",
            "message_id": message_id if 'message_id' in locals() else ""
        }

# =================== ROTAS DE AUTORIZAÇÃO ===================

@router.post("/whatsapp/authorize")
async def authorize_whatsapp_session(
    request: WhatsAppAuthorizationRequest,
    background_tasks: BackgroundTasks
):
    """
    Autorização de sessão WhatsApp - CORRIGIDA PARA SESSION_ID.
    
    NOVO FLUXO:
    1. Valida dados
    2. Salva autorização por session_id no Firebase
    3. DELEGA todo processamento para orchestration_service
    """
    try:
        logger.info(f"🚀 Autorizando sessão WhatsApp: {request.session_id}")
        
        # 1. Validar dados
        validated_phone = validate_phone_number(request.phone_number)
        validated_session = validate_session_id(request.session_id)
        
        # 2. Preparar dados da autorização
        expires_in = 3600  # 1 hora
        authorization_data = {
            "session_id": validated_session,
            "phone_number": validated_phone,
            "source": request.source,
            "authorized": True,
            "authorized_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat(),
            "user_data": request.user_data or {},
            "user_agent": request.user_agent,
            "page_url": request.page_url,
            "timestamp": request.timestamp,
            "lead_type": "landing_chat_lead" if request.source == "landing_chat" else "whatsapp_button_lead"
        }
        
        # 3. Salvar autorização por session_id (background task)
        background_tasks.add_task(save_session_authorization, validated_session, authorization_data)
        
        # 4. DELEGAR processamento para orchestration_service
        auth_data_for_orchestrator = {
            "session_id": validated_session,
            "phone_number": validated_phone,
            "source": request.source,
            "user_data": request.user_data or {}
        }
        
        background_tasks.add_task(
            intelligent_orchestrator.handle_whatsapp_authorization,
            auth_data_for_orchestrator
        )
        
        # 5. Log
        source_descriptions = {
            "landing_chat": "Chat da landing page completado",
            "landing_button": "Botão WhatsApp direto da landing",
            "landing_page": "Landing page geral"
        }
        source_msg = source_descriptions.get(request.source, request.source)
        
        logger.info(f"✅ Autorização criada e delegada | Session: {validated_session} | Origem: {source_msg}")
        
        # 6. Resposta
        return WhatsAppAuthorizationResponse(
            status="authorized",
            session_id=validated_session,
            phone_number=validated_phone,
            source=request.source,
            message=f"Sessão {validated_session} autorizada - {source_msg}. Usuário deve incluir session_id nas mensagens.",
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

# =================== ROTAS DE CONSULTA ===================

@router.get("/whatsapp/check-auth/{session_id}")
async def check_whatsapp_authorization(session_id: str):
    """
    Verifica se um session_id está autorizado
    """
    try:
        logger.info(f"📱 Verificando autorização: {session_id}")
        
        auth_check = await is_session_authorized(session_id)
        
        status_msg = "AUTORIZADO - Bot pode responder" if auth_check["authorized"] else "NÃO AUTORIZADO - Bot vai ignorar"
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
    """
    Revoga a autorização de um session_id
    """
    try:
        validated_session = validate_session_id(session_id)
        
        # Remover do Firebase
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
    """
    Obtém informações detalhadas sobre uma sessão WhatsApp
    """
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

# =================== ROTAS DE SERVIÇO BAILEYS ===================

@router.post("/whatsapp/send")
async def send_whatsapp_message(request: dict):
    """Enviar mensagem WhatsApp manualmente via Baileys."""
    try:
        phone_number = request.get("phone_number", "")
        message = request.get("message", "")
        
        if not phone_number or not message:
            raise HTTPException(
                status_code=400, 
                detail="Missing phone_number or message"
            )

        logger.info(f"📤 Envio manual WhatsApp para {phone_number}")
        success = await send_baileys_message(phone_number, message)

        if success:
            logger.info(f"✅ Mensagem enviada com sucesso para {phone_number}")
            return {
                "status": "success",
                "message": "WhatsApp message sent successfully",
                "to": phone_number
            }
        
        logger.error(f"❌ Falha ao enviar mensagem para {phone_number}")
        raise HTTPException(status_code=500, detail="Failed to send WhatsApp message")

    except Exception as e:
        logger.error(f"❌ Erro ao enviar mensagem: {str(e)}")
        raise HTTPException(status_code=500, detail=f"WhatsApp message sending error: {str(e)}")

@router.post("/whatsapp/start")
async def start_whatsapp_service():
    """Iniciar o serviço Baileys WhatsApp."""
    try:
        logger.info("🚀 Iniciando serviço Baileys WhatsApp...")
        success = await baileys_service.start_whatsapp_service()

        if success:
            logger.info("✅ Serviço Baileys WhatsApp iniciado com sucesso")
            return {
                "status": "success",
                "message": "Baileys WhatsApp service started successfully",
                "note": "Check console for QR code if first time setup"
            }
        
        logger.error("❌ Falha ao iniciar serviço WhatsApp")
        raise HTTPException(status_code=500, detail="Failed to start WhatsApp service")

    except Exception as e:
        logger.error(f"❌ Erro ao iniciar serviço WhatsApp: {str(e)}")
        raise HTTPException(status_code=500, detail=f"WhatsApp service start error: {str(e)}")

@router.get("/whatsapp/status")
async def whatsapp_status():
    """Obter status abrangente do serviço WhatsApp."""
    try:
        status = await get_baileys_status()
        logger.info(f"📊 Status WhatsApp verificado: {status.get('status', 'unknown')}")
        return status
    except Exception as e:
        logger.error(f"❌ Erro ao obter status WhatsApp: {str(e)}")
        return {
            "service": "baileys_whatsapp", 
            "status": "error", 
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# =================== ROTAS LEGADAS (MANTIDAS PARA COMPATIBILIDADE) ===================

@router.post("/whatsapp/authorize-session")
async def authorize_whatsapp_session_legacy(request: dict):
    """
    LEGADO: Mantido para compatibilidade com código existente
    Use /whatsapp/authorize para nova implementação
    """
    try:
        session_id = request.get("session_id", "")
        phone_number = request.get("phone_number", "")
        source = request.get("source", "landing_button")
        user_data = request.get("user_data", {})
        
        if not session_id:
            import time, random
            session_id = f"whatsapp_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Usar nova implementação internamente
        auth_request = WhatsAppAuthorizationRequest(
            session_id=session_id,
            phone_number=phone_number,
            source=source,
            user_data=user_data
        )
        
        validated_phone = validate_phone_number(phone_number)
        validated_session = validate_session_id(session_id)
        
        authorization_data = {
            "session_id": validated_session,
            "phone_number": validated_phone,
            "source": source,
            "authorized": True,
            "authorized_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(seconds=3600)).isoformat(),
            "user_data": user_data,
            "timestamp": datetime.utcnow().isoformat(),
            "lead_type": "landing_chat_lead" if source == "landing_chat" else "whatsapp_button_lead"
        }
        
        await save_authorization(validated_phone, authorization_data)
        
        logger.info(f"✅ Sessão WhatsApp autorizada (legado): {session_id}")
        
        return {
            "status": "authorized",
            "session_id": validated_session,
            "phone_number": validated_phone,
            "source": source,
            "message": "WhatsApp session authorized successfully (legacy)",
            "whatsapp_url": f"https://wa.me/{validated_phone}",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Erro ao autorizar sessão (legado): {str(e)}")
        return {
            "status": "error",
            "message": "Failed to authorize WhatsApp session",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# =================== ROTAS DE DEBUG E TESTE ===================

@router.get("/whatsapp/debug/active-auths")
async def list_active_authorizations():
    """
    Lista todas as autorizações ativas (para debug)
    """
    try:
        return {
            "message": "Lista de autorizações ativas",
            "note": "Implementar busca no Firebase conforme necessário",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@router.post("/whatsapp/debug/test-flows")
async def test_whatsapp_flows(request: dict):
    """
    Testa os fluxos do WhatsApp
    """
    try:
        test_phone = request.get("phone_number", "5511999999999")
        
        return {
            "status": "test_info",
            "message": "Fluxos disponíveis para teste",
            "flows": {
                "landing_chat": {
                    "description": "Chat da landing → Bot envia WhatsApp → Não permite conversa",
                    "test_data": {
                        "session_id": f"test_landing_{int(datetime.now().timestamp())}",
                        "phone_number": test_phone,
                        "source": "landing_chat",
                        "user_data": {
                            "name": "João Teste",
                            "email": "joao@teste.com",
                            "problem": "Divórcio consensual"
                        }
                    }
                },
                "landing_button": {
                    "description": "Botão WhatsApp → Usuário envia mensagem → Conversa contínua",
                    "test_data": {
                        "session_id": f"test_button_{int(datetime.now().timestamp())}",
                        "phone_number": test_phone,
                        "source": "landing_button"
                    }
                }
            },
            "note": "Use POST /whatsapp/authorize com os test_data para testar"
        }
        
    except Exception as e:
        return {
            "status": "test_failed",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }