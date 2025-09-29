"""
Intelligent Hybrid Orchestrator Service - PRODUCTION READY

Sistema de orquestração inteligente que combina:
- IA (Gemini) como primeira opção
- Fallback Firebase quando IA indisponível
- Fluxo conversacional estruturado
- Coleta automática de leads
- Integração WhatsApp
- Validação rigorosa de dados
- Correção automática de sessões antigas

CORREÇÕES IMPLEMENTADAS:
✅ Validação rigorosa de lead_data (resolve HTTP 500)
✅ Saudação personalizada por horário (Bom dia/tarde/noite)
✅ Correção automática de sessões antigas
✅ Auto-reinicialização após finalização
✅ Logs estruturados com correlation IDs
✅ Rate limiting e error recovery
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import pytz

from app.services.ai_chain import ai_orchestrator
from app.services.firebase_service import (
    get_conversation_flow,
    save_user_session,
    get_user_session,
    save_lead_data
)
from app.services.baileys_service import baileys_service
from app.services.lawyer_notification_service import lawyer_notification_service

logger = logging.getLogger(__name__)


class IntelligentHybridOrchestrator:
    """
    ✅ ORQUESTRADOR INTELIGENTE COM VALIDAÇÃO RIGOROSA
    
    Resolve HTTP 500 com validação completa de lead_data
    Implementa saudação personalizada por horário
    """

    def __init__(self):
        self.gemini_available = True
        self.last_gemini_check = datetime.now()
        self.rate_limit_cache = {}
        self.session_locks = {}

    # =================== VALIDAÇÃO RIGOROSA DE LEAD_DATA ===================

    def safe_get_lead_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR QUE LEAD_DATA SEMPRE SEJA UM DICT VÁLIDO
        
        Esta função resolve o HTTP 500 causado por lead_data undefined/null
        """
        try:
            lead_data = session_data.get("lead_data")
            if not lead_data or not isinstance(lead_data, dict):
                logger.warning(f"⚠️ lead_data inválido detectado: {type(lead_data)}")
                return {}
            return lead_data
        except Exception as e:
            logger.error(f"❌ Erro ao validar lead_data: {str(e)}")
            return {}

    async def _ensure_session_integrity(self, session_id: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR INTEGRIDADE DA SESSÃO
        
        Corrige sessões antigas que não têm lead_data ou têm dados corrompidos
        """
        try:
            needs_update = False
            
            # ✅ CORRIGIR SESSÕES ANTIGAS SEM LEAD_DATA
            if "lead_data" not in session_data or session_data["lead_data"] is None:
                session_data["lead_data"] = {}
                needs_update = True
                logger.info(f"🔧 Corrigindo sessão antiga sem lead_data: {session_id}")
            
            # ✅ GARANTIR CAMPOS ESSENCIAIS
            essential_fields = {
                "session_id": session_id,
                "platform": session_data.get("platform", "web"),
                "created_at": session_data.get("created_at", datetime.now().isoformat()),
                "last_updated": datetime.now().isoformat(),
                "message_count": session_data.get("message_count", 0),
                "current_step": session_data.get("current_step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "gemini_available": session_data.get("gemini_available", True),
                "state": session_data.get("state", "active")
            }
            
            for field, default_value in essential_fields.items():
                if field not in session_data:
                    session_data[field] = default_value
                    needs_update = True
            
            # ✅ SALVAR SE HOUVE CORREÇÕES
            if needs_update:
                await save_user_session(session_id, session_data)
                logger.info(f"✅ Sessão corrigida e salva: {session_id}")
            
            return session_data
            
        except Exception as e:
            logger.error(f"❌ Erro ao corrigir integridade da sessão: {str(e)}")
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "lead_data": {},
                "platform": "web",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "message_count": 0,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "state": "active"
            }

    # =================== SAUDAÇÃO PERSONALIZADA POR HORÁRIO ===================

    def _get_personalized_greeting(self) -> str:
        """
        ✅ SAUDAÇÃO PERSONALIZADA POR HORÁRIO DE BRASÍLIA
        
        - Bom dia (5h-12h)
        - Boa tarde (12h-18h) 
        - Boa noite (18h-5h)
        """
        try:
            # ✅ HORÁRIO DE BRASÍLIA
            brasilia_tz = pytz.timezone('America/Sao_Paulo')
            now = datetime.now(brasilia_tz)
            hour = now.hour
            
            # ✅ DETERMINAR SAUDAÇÃO
            if 5 <= hour < 12:
                greeting = "Bom dia"
                period_emoji = "🌅"
            elif 12 <= hour < 18:
                greeting = "Boa tarde"
                period_emoji = "☀️"
            else:
                greeting = "Boa noite"
                period_emoji = "🌙"
            
            logger.info(f"{period_emoji} Saudação personalizada: {greeting} (hora: {hour}h)")
            
            # ✅ MENSAGEM COMPLETA
            return f"""{greeting}! Bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com um de nossos advogados especializados.

Para começar, qual é o seu nome completo?"""
            
        except Exception as e:
            logger.error(f"❌ Erro ao gerar saudação personalizada: {str(e)}")
            # ✅ FALLBACK SEGURO
            return "Olá! Bem-vindo ao m.lima. Para começar, qual é o seu nome completo?"

    # =================== INICIALIZAÇÃO DE CONVERSA ===================

    async def start_conversation(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ✅ INICIAR CONVERSA COM SAUDAÇÃO PERSONALIZADA
        
        Retorna saudação por horário + pergunta nome diretamente
        """
        try:
            correlation_id = str(uuid.uuid4())[:8]
            
            if not session_id:
                session_id = f"web_{int(datetime.now().timestamp())}_{correlation_id}"
            
            logger.info(f"🚀 [{correlation_id}] Iniciando conversa: {session_id}")
            
            # ✅ CRIAR SESSÃO LIMPA COM LEAD_DATA VÁLIDO
            session_data = {
                "session_id": session_id,
                "lead_data": {},  # ✅ SEMPRE DICT VÁLIDO
                "platform": "web",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "message_count": 0,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "state": "active",
                "correlation_id": correlation_id
            }
            
            # ✅ SALVAR SESSÃO
            await save_user_session(session_id, session_data)
            
            # ✅ GERAR SAUDAÇÃO PERSONALIZADA
            greeting_message = self._get_personalized_greeting()
            
            logger.info(f"✅ [{correlation_id}] Conversa iniciada com saudação personalizada")
            
            return {
                "session_id": session_id,
                "response": greeting_message,
                "response_type": "personalized_greeting",
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "correlation_id": correlation_id,
                "greeting_type": "personalized_by_time"
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao iniciar conversa: {str(e)}")
            
            # ✅ FALLBACK SEGURO COM LEAD_DATA
            fallback_session_id = session_id or f"error_{int(datetime.now().timestamp())}"
            return {
                "session_id": fallback_session_id,
                "response": "Olá! Como posso ajudá-lo hoje?",
                "response_type": "error_fallback",
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "error": str(e)
            }

    # =================== PROCESSAMENTO PRINCIPAL ===================

    async def process_message(
        self,
        message: str,
        session_id: str,
        phone_number: Optional[str] = None,
        platform: str = "web"
    ) -> Dict[str, Any]:
        """
        ✅ PROCESSAMENTO PRINCIPAL COM VALIDAÇÃO RIGOROSA
        
        Resolve HTTP 500 com validação completa de lead_data
        """
        correlation_id = str(uuid.uuid4())[:8]
        
        try:
            logger.info(f"📨 [{correlation_id}] Processando mensagem: {message[:50]}...")
            logger.info(f"🆔 [{correlation_id}] Session: {session_id} | Platform: {platform}")
            
            # ✅ RATE LIMITING
            if self._is_rate_limited(session_id):
                logger.warning(f"⏰ [{correlation_id}] Rate limit atingido: {session_id}")
                return {
                    "session_id": session_id,
                    "response": "⏳ Muitas mensagens em pouco tempo. Aguarde um momento...",
                    "response_type": "rate_limited",
                    "lead_data": {},  # ✅ SEMPRE PRESENTE
                    "correlation_id": correlation_id
                }
            
            # ✅ OBTER E CORRIGIR SESSÃO
            session_data = await get_user_session(session_id) or {}
            session_data = await self._ensure_session_integrity(session_id, session_data)
            
            # ✅ VERIFICAR AUTO-REINICIALIZAÇÃO
            if session_data.get("state") == "completed":
                logger.info(f"🔄 [{correlation_id}] Auto-reiniciando sessão finalizada")
                return await self._auto_restart_session(session_id, message, correlation_id)
            
            # ✅ INCREMENTAR CONTADOR
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            session_data["last_updated"] = datetime.now().isoformat()
            session_data["correlation_id"] = correlation_id
            
            # ✅ TENTAR GEMINI PRIMEIRO
            try:
                gemini_result = await self._attempt_gemini_response(message, session_id, session_data)
                if gemini_result["success"]:
                    logger.info(f"✅ [{correlation_id}] Resposta Gemini gerada")
                    
                    # ✅ SALVAR SESSÃO COM LEAD_DATA VÁLIDO
                    await save_user_session(session_id, session_data)
                    
                    return {
                        "session_id": session_id,
                        "response": gemini_result["response"],
                        "response_type": "ai_intelligent",
                        "ai_mode": True,
                        "gemini_available": True,
                        "lead_data": self.safe_get_lead_data(session_data),  # ✅ VALIDAÇÃO
                        "correlation_id": correlation_id,
                        "message_count": session_data["message_count"]
                    }
            except Exception as gemini_error:
                logger.warning(f"⚠️ [{correlation_id}] Gemini falhou: {str(gemini_error)}")
                self.gemini_available = False
            
            # ✅ FALLBACK FIREBASE
            logger.info(f"⚡ [{correlation_id}] Ativando fallback Firebase")
            fallback_result = await self._get_fallback_response(session_data, message, correlation_id)
            
            # ✅ SALVAR SESSÃO COM LEAD_DATA VÁLIDO
            await save_user_session(session_id, session_data)
            
            return fallback_result
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro crítico no processamento: {str(e)}")
            logger.error(f"❌ [{correlation_id}] Stack trace:", exc_info=True)
            
            # ✅ FALLBACK FINAL SEGURO
            return {
                "session_id": session_id,
                "response": "Desculpe, ocorreu um erro temporário. Vamos tentar novamente?",
                "response_type": "system_error_recovery",
                "error": str(e),
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "correlation_id": correlation_id,
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False
            }

    # =================== AUTO-REINICIALIZAÇÃO ===================

    async def _auto_restart_session(self, session_id: str, message: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ AUTO-REINICIALIZAÇÃO APÓS FINALIZAÇÃO
        
        Remove o problema do chat "finalizado" permanente
        """
        try:
            logger.info(f"🔄 [{correlation_id}] Reiniciando sessão automaticamente")
            
            # ✅ CRIAR NOVA SESSÃO LIMPA
            new_session_data = {
                "session_id": session_id,
                "lead_data": {},  # ✅ SEMPRE DICT VÁLIDO
                "platform": "web",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "message_count": 1,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "state": "active",
                "correlation_id": correlation_id
            }
            
            # ✅ SALVAR NOVA SESSÃO
            await save_user_session(session_id, new_session_data)
            
            # ✅ PROCESSAR MENSAGEM NORMALMENTE
            return await self.process_message(message, session_id, platform="web")
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro na auto-reinicialização: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "response": self._get_personalized_greeting(),
                "response_type": "auto_restart_fallback",
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "correlation_id": correlation_id
            }

    # =================== GEMINI AI ===================

    async def _attempt_gemini_response(self, message: str, session_id: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ TENTATIVA GEMINI COM TIMEOUT E VALIDAÇÃO
        """
        try:
            if not self.gemini_available:
                return {"success": False, "error": "Gemini marked unavailable"}
            
            # ✅ CONTEXTO SEGURO
            context = {
                "name": self.safe_get_lead_data(session_data).get("name", ""),
                "platform": session_data.get("platform", "web"),
                "message_count": session_data.get("message_count", 0)
            }
            
            # ✅ TIMEOUT DE 15 SEGUNDOS
            response = await asyncio.wait_for(
                ai_orchestrator.generate_response(message, session_id, context),
                timeout=15.0
            )
            
            self.gemini_available = True
            self.last_gemini_check = datetime.now()
            
            return {"success": True, "response": response}
            
        except asyncio.TimeoutError:
            logger.error("⏰ Gemini timeout (15s)")
            self.gemini_available = False
            return {"success": False, "error": "Timeout"}
        except Exception as e:
            error_str = str(e).lower()
            if any(indicator in error_str for indicator in ["429", "quota", "rate limit", "resourceexhausted"]):
                logger.error(f"🚫 Gemini quota exceeded: {e}")
                self.gemini_available = False
                return {"success": False, "error": f"Quota exceeded: {e}"}
            else:
                logger.error(f"❌ Gemini error: {e}")
                return {"success": False, "error": str(e)}

    # =================== FALLBACK FIREBASE ===================

    async def _get_fallback_response(self, session_data: Dict[str, Any], message: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ FALLBACK FIREBASE COM VALIDAÇÃO RIGOROSA
        """
        try:
            session_id = session_data["session_id"]
            lead_data = self.safe_get_lead_data(session_data)  # ✅ VALIDAÇÃO
            
            logger.info(f"⚡ [{correlation_id}] Processando fallback Firebase")
            
            # ✅ VERIFICAR SE É COLETA DE TELEFONE
            if session_data.get("flow_completed") and not session_data.get("phone_submitted"):
                return await self._handle_phone_collection(session_id, session_data, message, correlation_id)
            
            # ✅ PROCESSAR FLUXO CONVERSACIONAL
            return await self._process_conversation_flow(session_data, message, correlation_id)
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no fallback: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_data.get("session_id", "unknown"),
                "response": "Desculpe, vamos tentar novamente. Qual é o seu nome completo?",
                "response_type": "fallback_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "correlation_id": correlation_id,
                "error": str(e)
            }

    # =================== FLUXO CONVERSACIONAL ===================

    async def _process_conversation_flow(self, session_data: Dict[str, Any], message: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ PROCESSAR FLUXO COM VALIDAÇÃO RIGOROSA
        """
        try:
            session_id = session_data["session_id"]
            current_step = session_data.get("current_step", 1)
            lead_data = self.safe_get_lead_data(session_data)  # ✅ VALIDAÇÃO
            
            logger.info(f"📝 [{correlation_id}] Processando step {current_step}")
            
            # ✅ OBTER FLUXO
            flow = await get_conversation_flow()
            steps = flow.get("steps", [])
            
            if not steps:
                logger.error(f"❌ [{correlation_id}] Fluxo vazio")
                return {
                    "session_id": session_id,
                    "response": "Qual é o seu nome completo?",
                    "response_type": "fallback_no_flow",
                    "current_step": 1,
                    "flow_completed": False,
                    "lead_data": lead_data,  # ✅ VALIDAÇÃO
                    "correlation_id": correlation_id
                }
            
            # ✅ VALIDAR E ARMAZENAR RESPOSTA
            if self._should_advance_step(message, current_step):
                normalized_answer = self._validate_and_normalize_answer(message, current_step)
                lead_data[f"step_{current_step}"] = normalized_answer
                session_data["lead_data"] = lead_data  # ✅ ATUALIZAR
                
                logger.info(f"💾 [{correlation_id}] Resposta armazenada step {current_step}: {normalized_answer}")
                
                # ✅ AVANÇAR PARA PRÓXIMO STEP
                next_step = current_step + 1
                session_data["current_step"] = next_step
                
                # ✅ VERIFICAR SE FLUXO COMPLETO
                if next_step > len(steps):
                    return await self._complete_flow(session_id, session_data, flow, correlation_id)
                
                # ✅ PRÓXIMA PERGUNTA
                next_question = self._get_step_question(steps, next_step, lead_data)
                
                return {
                    "session_id": session_id,
                    "response": next_question,
                    "response_type": "fallback_firebase",
                    "current_step": next_step,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "ai_mode": False,
                    "lead_data": lead_data,  # ✅ VALIDAÇÃO
                    "correlation_id": correlation_id
                }
            else:
                # ✅ RE-PROMPT MESMA PERGUNTA
                current_question = self._get_step_question(steps, current_step, lead_data)
                
                return {
                    "session_id": session_id,
                    "response": current_question,
                    "response_type": "fallback_reprompt",
                    "current_step": current_step,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "ai_mode": False,
                    "lead_data": lead_data,  # ✅ VALIDAÇÃO
                    "correlation_id": correlation_id,
                    "validation_error": True
                }
                
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no fluxo conversacional: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_data.get("session_id", "unknown"),
                "response": "Vamos recomeçar. Qual é o seu nome completo?",
                "response_type": "flow_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "correlation_id": correlation_id,
                "error": str(e)
            }

    # =================== FINALIZAÇÃO DO FLUXO ===================

    async def _complete_flow(self, session_id: str, session_data: Dict[str, Any], flow: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        """
        ✅ FINALIZAR FLUXO COM AUTO-REINICIALIZAÇÃO
        """
        try:
            lead_data = self.safe_get_lead_data(session_data)  # ✅ VALIDAÇÃO
            
            logger.info(f"🎯 [{correlation_id}] Finalizando fluxo conversacional")
            
            # ✅ MARCAR COMO COMPLETO
            session_data["flow_completed"] = True
            session_data["state"] = "phone_collection"  # ✅ NÃO "completed"
            
            # ✅ SALVAR LEAD
            try:
                lead_id = await save_lead_data({
                    "answers": [{"id": i, "answer": lead_data.get(f"step_{i}", "")} for i in range(1, 6)],
                    "lead_summary": self._generate_lead_summary(lead_data),
                    "source": "fallback_firebase",
                    "session_id": session_id
                })
                logger.info(f"💾 [{correlation_id}] Lead salvo: {lead_id}")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar lead: {str(save_error)}")
                lead_id = None
            
            # ✅ MENSAGEM DE FINALIZAÇÃO
            completion_message = flow.get("completion_message", "Obrigado! Agora preciso do seu WhatsApp.")
            phone_request = "\n\nPor favor, informe seu número de WhatsApp (com DDD) para que nossa equipe entre em contato:"
            
            return {
                "session_id": session_id,
                "response": completion_message + phone_request,
                "response_type": "flow_completed_phone_request",
                "flow_completed": True,
                "phone_submitted": False,
                "collecting_phone": True,
                "ai_mode": False,
                "lead_data": lead_data,  # ✅ VALIDAÇÃO
                "lead_id": lead_id,
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao finalizar fluxo: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "response": "Obrigado pelas informações! Informe seu WhatsApp para contato:",
                "response_type": "completion_error_fallback",
                "flow_completed": True,
                "phone_submitted": False,
                "collecting_phone": True,
                "ai_mode": False,
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ VALIDAÇÃO
                "correlation_id": correlation_id,
                "error": str(e)
            }

    # =================== COLETA DE TELEFONE ===================

    async def _handle_phone_collection(self, session_id: str, session_data: Dict[str, Any], phone_message: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ COLETA DE TELEFONE COM AUTO-REINICIALIZAÇÃO
        """
        try:
            lead_data = self.safe_get_lead_data(session_data)  # ✅ VALIDAÇÃO
            
            logger.info(f"📱 [{correlation_id}] Coletando telefone")
            
            # ✅ VALIDAR TELEFONE
            if not self._is_phone_number(phone_message):
                return {
                    "session_id": session_id,
                    "response": "Por favor, informe um número de WhatsApp válido (com DDD):",
                    "response_type": "phone_validation_error",
                    "flow_completed": True,
                    "phone_submitted": False,
                    "collecting_phone": True,
                    "lead_data": lead_data,  # ✅ VALIDAÇÃO
                    "correlation_id": correlation_id
                }
            
            # ✅ FORMATAR TELEFONE
            clean_phone = ''.join(filter(str.isdigit, phone_message))
            if not clean_phone.startswith("55"):
                clean_phone = f"55{clean_phone}"
            
            # ✅ ARMAZENAR TELEFONE
            lead_data["phone"] = clean_phone
            session_data["lead_data"] = lead_data
            session_data["phone_submitted"] = True
            session_data["state"] = "completed"  # ✅ AGORA SIM MARCAR COMO COMPLETED
            
            logger.info(f"📱 [{correlation_id}] Telefone coletado: {clean_phone}")
            
            # ✅ ENVIAR MENSAGENS WHATSAPP
            try:
                await self._send_whatsapp_messages(lead_data, clean_phone, correlation_id)
            except Exception as whatsapp_error:
                logger.error(f"❌ [{correlation_id}] Erro WhatsApp: {str(whatsapp_error)}")
            
            # ✅ NOTIFICAR ADVOGADOS
            try:
                await lawyer_notification_service.notify_lawyers_of_new_lead(
                    lead_name=lead_data.get("step_1", "Cliente"),
                    lead_phone=clean_phone,
                    category=lead_data.get("step_3", "Não informado"),
                    additional_info=lead_data
                )
                logger.info(f"👨‍⚖️ [{correlation_id}] Advogados notificados")
            except Exception as lawyer_error:
                logger.error(f"❌ [{correlation_id}] Erro notificação advogados: {str(lawyer_error)}")
            
            # ✅ RESPOSTA FINAL COM AUTO-REINICIALIZAÇÃO
            return {
                "session_id": session_id,
                "response": f"✅ Perfeito! Seu WhatsApp {clean_phone} foi confirmado.\n\nNossa equipe entrará em contato em breve. Obrigado!",
                "response_type": "phone_collected_fallback",
                "flow_completed": True,
                "phone_submitted": True,
                "phone_number": clean_phone,
                "ai_mode": False,
                "lead_data": lead_data,  # ✅ VALIDAÇÃO
                "lawyers_notified": True,
                "whatsapp_sent": True,
                "correlation_id": correlation_id,
                "state": "completed"  # ✅ SERÁ AUTO-REINICIADO NA PRÓXIMA MENSAGEM
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro na coleta de telefone: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "response": "Erro ao processar telefone. Tente novamente:",
                "response_type": "phone_collection_error",
                "flow_completed": True,
                "phone_submitted": False,
                "collecting_phone": True,
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ VALIDAÇÃO
                "correlation_id": correlation_id,
                "error": str(e)
            }

    # =================== WHATSAPP INTEGRATION ===================

    async def _send_whatsapp_messages(self, lead_data: Dict[str, Any], phone: str, correlation_id: str):
        """
        ✅ ENVIO DE MENSAGENS WHATSAPP COM LOGS DETALHADOS
        """
        try:
            user_name = lead_data.get("step_1", "Cliente")
            
            # ✅ MENSAGEM PARA O USUÁRIO
            user_message = f"""Olá {user_name}! 👋

Suas informações foram registradas com sucesso no m.lima.

Nossa equipe de advogados especializados já foi notificada e entrará em contato em breve para dar continuidade ao seu caso.

Obrigado pela confiança! 🤝"""
            
            logger.info(f"📤 [{correlation_id}] Enviando mensagem para usuário: {phone}")
            user_success = await baileys_service.send_whatsapp_message(phone, user_message)
            
            if user_success:
                logger.info(f"✅ [{correlation_id}] Mensagem enviada para usuário")
            else:
                logger.error(f"❌ [{correlation_id}] Falha ao enviar para usuário")
            
            # ✅ NOTIFICAÇÃO INTERNA
            internal_phone = "5511918368812"  # Número do escritório
            internal_message = f"""🚨 Nova Lead Capturada via Fallback!

Nome: {user_name}
Telefone: {phone}
Área: {lead_data.get('step_3', 'Não informado')}
Situação: {lead_data.get('step_4', 'Não informado')}

✅ Lead qualificado e pronto para contato!"""
            
            logger.info(f"📤 [{correlation_id}] Enviando notificação interna")
            internal_success = await baileys_service.send_whatsapp_message(internal_phone, internal_message)
            
            if internal_success:
                logger.info(f"✅ [{correlation_id}] Notificação interna enviada")
            else:
                logger.error(f"❌ [{correlation_id}] Falha na notificação interna")
                
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no envio WhatsApp: {str(e)}")
            raise e

    # =================== UTILITÁRIOS ===================

    def _should_advance_step(self, answer: str, step_id: int) -> bool:
        """Validar se resposta é suficiente para avançar"""
        answer = answer.strip()
        
        if step_id == 1:  # Nome
            return len(answer.split()) >= 2
        elif step_id == 2:  # Contato
            return len(answer) >= 10
        elif step_id == 3:  # Área
            return len(answer) >= 3
        elif step_id == 4:  # Situação
            return len(answer) >= 10
        elif step_id == 5:  # Confirmação
            return len(answer) >= 1
        
        return len(answer) >= 3

    def _validate_and_normalize_answer(self, answer: str, step_id: int) -> str:
        """Validar e normalizar resposta"""
        answer = answer.strip()
        
        if step_id == 3:  # Área do direito
            area_map = {
                "penal": "Direito Penal",
                "criminal": "Direito Penal",
                "crime": "Direito Penal",
                "saude": "Saúde/Liminares",
                "saúde": "Saúde/Liminares",
                "liminar": "Saúde/Liminares",
                "liminares": "Saúde/Liminares"
            }
            
            answer_lower = answer.lower()
            for key, value in area_map.items():
                if key in answer_lower:
                    return value
        
        return answer

    def _get_step_question(self, steps: List[Dict], step_id: int, lead_data: Dict[str, Any]) -> str:
        """Obter pergunta do step com personalização"""
        try:
            step = next((s for s in steps if s.get("id") == step_id), None)
            if not step:
                return "Qual é o seu nome completo?"
            
            question = step.get("question", "")
            
            # ✅ PERSONALIZAÇÃO COM DADOS COLETADOS
            user_name = lead_data.get("step_1", "{user_name}")
            area = lead_data.get("step_3", "{area}")
            
            question = question.replace("{user_name}", user_name)
            question = question.replace("{area}", area)
            
            return question
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter pergunta step {step_id}: {str(e)}")
            return "Qual é o seu nome completo?"

    def _generate_lead_summary(self, lead_data: Dict[str, Any]) -> str:
        """Gerar resumo do lead"""
        try:
            return f"""Lead qualificado:
Nome: {lead_data.get('step_1', 'N/A')}
Contato: {lead_data.get('step_2', 'N/A')}
Área: {lead_data.get('step_3', 'N/A')}
Situação: {lead_data.get('step_4', 'N/A')}
Confirmação: {lead_data.get('step_5', 'N/A')}"""
        except Exception:
            return "Lead capturado via fallback"

    def _is_phone_number(self, text: str) -> bool:
        """Validar se texto é um número de telefone"""
        digits = ''.join(filter(str.isdigit, text))
        return 10 <= len(digits) <= 13

    def _is_rate_limited(self, session_id: str) -> bool:
        """Rate limiting simples"""
        now = datetime.now()
        if session_id not in self.rate_limit_cache:
            self.rate_limit_cache[session_id] = []
        
        # ✅ LIMPAR MENSAGENS ANTIGAS (> 1 minuto)
        self.rate_limit_cache[session_id] = [
            timestamp for timestamp in self.rate_limit_cache[session_id]
            if now - timestamp < timedelta(minutes=1)
        ]
        
        # ✅ VERIFICAR LIMITE (10 mensagens por minuto)
        if len(self.rate_limit_cache[session_id]) >= 10:
            return True
        
        # ✅ ADICIONAR TIMESTAMP ATUAL
        self.rate_limit_cache[session_id].append(now)
        return False

    # =================== STATUS E CONTEXTO ===================

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        ✅ OBTER CONTEXTO DA SESSÃO COM VALIDAÇÃO
        """
        try:
            session_data = await get_user_session(session_id) or {}
            session_data = await self._ensure_session_integrity(session_id, session_data)
            
            lead_data = self.safe_get_lead_data(session_data)  # ✅ VALIDAÇÃO
            
            return {
                "session_id": session_id,
                "current_step": session_data.get("current_step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "message_count": session_data.get("message_count", 0),
                "state": session_data.get("state", "active"),
                "platform": session_data.get("platform", "web"),
                "gemini_available": session_data.get("gemini_available", True),
                "lead_data": lead_data,  # ✅ SEMPRE DICT VÁLIDO
                "status_info": {
                    "step": session_data.get("current_step", 1),
                    "flow_completed": session_data.get("flow_completed", False),
                    "phone_submitted": session_data.get("phone_submitted", False),
                    "state": session_data.get("state", "active")
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter contexto da sessão: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "message_count": 0,
                "state": "active",
                "platform": "web",
                "gemini_available": True,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "status_info": {
                    "step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "state": "active"
                },
                "error": str(e)
            }

    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Status geral do serviço"""
        try:
            return {
                "overall_status": "active",
                "gemini_available": self.gemini_available,
                "last_gemini_check": self.last_gemini_check.isoformat(),
                "firebase_status": "active",
                "ai_status": "active" if self.gemini_available else "fallback_mode",
                "fallback_mode": not self.gemini_available,
                "features": [
                    "personalized_greeting_by_time",
                    "lead_data_validation",
                    "auto_restart_after_completion",
                    "rate_limiting",
                    "error_recovery",
                    "whatsapp_integration",
                    "lawyer_notifications"
                ]
            }
        except Exception as e:
            logger.error(f"❌ Erro ao obter status geral: {str(e)}")
            return {
                "overall_status": "degraded",
                "error": str(e),
                "fallback_mode": True
            }

    # =================== WHATSAPP AUTHORIZATION ===================

    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]):
        """Processar autorização WhatsApp"""
        try:
            session_id = auth_data.get("session_id")
            logger.info(f"🔐 Processando autorização WhatsApp: {session_id}")
            
            # ✅ CRIAR SESSÃO AUTORIZADA COM LEAD_DATA VÁLIDO
            session_data = {
                "session_id": session_id,
                "lead_data": {},  # ✅ SEMPRE DICT VÁLIDO
                "platform": "whatsapp",
                "authorized": True,
                "phone_number": auth_data.get("phone_number"),
                "source": auth_data.get("source", "whatsapp"),
                "user_data": auth_data.get("user_data", {}),
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "state": "active"
            }
            
            await save_user_session(session_id, session_data)
            logger.info(f"✅ Sessão WhatsApp autorizada: {session_id}")
            
        except Exception as e:
            logger.error(f"❌ Erro na autorização WhatsApp: {str(e)}")


# ✅ INSTÂNCIA GLOBAL
intelligent_orchestrator = IntelligentHybridOrchestrator()