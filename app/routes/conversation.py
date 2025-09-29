"""
Conversation Routes

Routes for handling conversation flow and chat interactions.
These routes manage the guided conversation flow for lead qualification.
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.models.request import ConversationRequest
from app.services.orchestration_service import intelligent_orchestrator

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


@router.post("/conversation/start")
async def start_conversation(session_id: Optional[str] = None):
    """
    ✅ INICIAR CONVERSA COM SAUDAÇÃO PERSONALIZADA POR HORÁRIO
    
    Inicia uma nova conversa com saudação baseada no horário:
    - Bom dia (5h-12h)
    - Boa tarde (12h-18h) 
    - Boa noite (18h-5h)
    
    Seguido da pergunta do nome completo.
    """
    try:
        logger.info("🚀 Iniciando nova conversa com saudação personalizada")
        
        # ✅ USAR ORCHESTRATOR PARA SAUDAÇÃO PERSONALIZADA
        result = await intelligent_orchestrator.start_conversation(session_id)
        
        logger.info(f"✅ Conversa iniciada: {result.get('session_id')}")
        logger.info(f"💬 Saudação: {result.get('response', '')[:50]}...")
        
        return JSONResponse(
            content=result,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar conversa: {str(e)}")
        logger.error(f"❌ Stack trace:", exc_info=True)
        
        # ✅ FALLBACK COM LEAD_DATA VÁLIDO
        fallback_response = {
            "session_id": f"error_{hash(str(e)) % 10000}",
            "response": "Olá! Como posso ajudá-lo hoje?",
            "response_type": "error_fallback",
            "error": str(e),
            "lead_data": {}  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
        }
        
        return JSONResponse(
            content=fallback_response,
            status_code=200,  # Não retornar 500 para não quebrar frontend
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )


@router.post("/conversation/respond")
async def respond_to_conversation(request: ConversationRequest):
    """
    ✅ PROCESSAR RESPOSTA COM VALIDAÇÃO RIGOROSA DE LEAD_DATA
    
    Processa resposta do usuário com:
    - Validação rigorosa de lead_data
    - Correção automática de sessões antigas
    - Fallback seguro em caso de erro
    - Sempre retorna lead_data válido
    """
    try:
        logger.info(f"📨 Processando resposta: {request.message[:50]}...")
        logger.info(f"🆔 Session ID: {request.session_id}")
        
        # ✅ PROCESSAR VIA ORCHESTRATOR COM VALIDAÇÃO RIGOROSA
        result = await intelligent_orchestrator.process_message(
            message=request.message,
            session_id=request.session_id or f"web_{hash(request.message) % 10000}",
            platform="web"
        )
        
        # ✅ GARANTIR LEAD_DATA SEMPRE PRESENTE
        if "lead_data" not in result:
            result["lead_data"] = {}
            logger.warning("⚠️ lead_data ausente no resultado, adicionado automaticamente")
        
        logger.info(f"✅ Resposta processada: {result.get('response_type', 'unknown')}")
        logger.info(f"📊 Lead data presente: {bool(result.get('lead_data'))}")
        
        return JSONResponse(
            content=result,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Erro ao processar resposta: {str(e)}")
        logger.error(f"❌ Request data: message='{request.message}', session_id='{request.session_id}'")
        logger.error(f"❌ Stack trace:", exc_info=True)
        
        # ✅ FALLBACK SEGURO COM LEAD_DATA VÁLIDO
        error_response = {
            "session_id": request.session_id or f"error_{hash(str(e)) % 10000}",
            "response": "Desculpe, ocorreu um erro temporário. Vamos tentar novamente?",
            "response_type": "system_error_recovery",
            "error": str(e),
            "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
            "step": 1,
            "flow_completed": False,
            "ai_mode": False
        }
        
        return JSONResponse(
            content=error_response,
            status_code=200,  # ✅ NÃO RETORNAR 500 PARA NÃO QUEBRAR FRONTEND
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )


@router.get("/conversation/status/{session_id}")
async def get_conversation_status(session_id: str):
    """
    ✅ OBTER STATUS DA CONVERSA COM VALIDAÇÃO DE LEAD_DATA
    
    Retorna status completo da conversa com:
    - Validação de integridade da sessão
    - lead_data sempre presente
    - Correção automática de sessões antigas
    """
    try:
        logger.info(f"📊 Obtendo status da conversa: {session_id}")
        
        # ✅ OBTER CONTEXTO VIA ORCHESTRATOR
        context = await intelligent_orchestrator.get_session_context(session_id)
        
        # ✅ GARANTIR LEAD_DATA SEMPRE PRESENTE
        if "lead_data" not in context:
            context["lead_data"] = {}
            logger.warning("⚠️ lead_data ausente no contexto, adicionado automaticamente")
        
        logger.info(f"✅ Status obtido: {context.get('current_step', 'unknown')}")
        
        return JSONResponse(
            content=context,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Erro ao obter status: {str(e)}")
        logger.error(f"❌ Stack trace:", exc_info=True)
        
        # ✅ FALLBACK SEGURO
        error_context = {
            "session_id": session_id,
            "error": str(e),
            "status_info": {
                "step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "state": "error"
            },
            "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
            "current_step": 1,
            "flow_completed": False,
            "phone_submitted": False
        }
        
        return JSONResponse(
            content=error_context,
            status_code=200,  # ✅ NÃO RETORNAR 500
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )


@router.get("/conversation/flow")
async def get_conversation_flow():
    """
    ✅ OBTER FLUXO DE CONVERSA
    
    Retorna o fluxo de conversa configurado no Firebase.
    """
    try:
        from app.services.firebase_service import get_conversation_flow
        
        logger.info("📋 Obtendo fluxo de conversa")
        
        flow = await get_conversation_flow()
        
        logger.info(f"✅ Fluxo obtido: {len(flow.get('steps', []))} steps")
        
        return JSONResponse(
            content=flow,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Erro ao obter fluxo: {str(e)}")
        
        # ✅ FALLBACK COM FLUXO BÁSICO
        fallback_flow = {
            "steps": [
                {"id": 1, "question": "Qual é o seu nome completo?"},
                {"id": 2, "question": "Qual o seu telefone e e-mail?"},
                {"id": 3, "question": "Em qual área você precisa de ajuda?"},
                {"id": 4, "question": "Descreva sua situação:"},
                {"id": 5, "question": "Posso direcioná-lo para nosso especialista?"}
            ],
            "completion_message": "Obrigado! Nossa equipe entrará em contato.",
            "error": str(e)
        }
        
        return JSONResponse(
            content=fallback_flow,
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )


@router.post("/conversation/reset-session/{session_id}")
async def reset_session(session_id: str):
    """
    ✅ RESETAR SESSÃO COMPLETAMENTE
    
    Limpa sessão e permite nova conversa.
    Remove o problema de "finalizado" permanente.
    """
    try:
        logger.info(f"🔄 Resetando sessão: {session_id}")
        
        # ✅ CRIAR NOVA SESSÃO LIMPA
        result = await intelligent_orchestrator.start_conversation(session_id)
        
        logger.info(f"✅ Sessão resetada: {session_id}")
        
        return JSONResponse(
            content={
                "success": True,
                "message": "Sessão resetada com sucesso",
                "session_id": session_id,
                "new_conversation": result
            },
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Erro ao resetar sessão: {str(e)}")
        
        return JSONResponse(
            content={
                "success": False,
                "error": str(e),
                "session_id": session_id
            },
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization"
            }
        )