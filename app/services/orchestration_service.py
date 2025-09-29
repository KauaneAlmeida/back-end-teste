"""
Intelligent Hybrid Orchestrator - CLOUD RUN OPTIMIZED

Sistema de orquestração inteligente otimizado para Google Cloud Run com:
- Timeouts ultra agressivos (2-3s máximo)
- Fallback instantâneo em caso de timeout
- Processamento assíncrono não-bloqueante
- Health checks rápidos
- Memory management otimizado
"""

import os
import re
import json
import uuid
import asyncio
import logging
import pytz
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from collections import defaultdict

# Import services
from app.services.firebase_service import (
    get_conversation_flow, 
    save_user_session, 
    get_user_session,
    save_lead_data
)
from app.services.baileys_service import baileys_service
from app.services.lawyer_notification_service import lawyer_notification_service
from app.services.ai_chain import ai_orchestrator

# Configure logging
logger = logging.getLogger(__name__)

class IntelligentHybridOrchestrator:
    """
    ✅ ORQUESTRADOR HÍBRIDO - CLOUD RUN ULTRA OTIMIZADO
    
    Timeouts ultra agressivos para evitar timeout do Cloud Run:
    - Gemini: 2s (era 4s)
    - Firebase: 1.5s (era 3s) 
    - WhatsApp: 3s (era 6s)
    - Global: 8s (era 15s)
    """
    
    def __init__(self):
        # ⚡ TIMEOUTS ULTRA AGRESSIVOS PARA CLOUD RUN
        self.gemini_timeout = 2.0      # ✅ REDUZIDO DE 4s PARA 2s
        self.firebase_timeout = 1.5    # ✅ REDUZIDO DE 3s PARA 1.5s
        self.whatsapp_timeout = 3.0    # ✅ REDUZIDO DE 6s PARA 3s
        self.whatsapp_global_timeout = 8.0  # ✅ REDUZIDO DE 15s PARA 8s
        self.notification_timeout = 4.0     # ✅ REDUZIDO DE 8s PARA 4s
        self.total_request_timeout = 25.0   # ✅ LIMITE TOTAL PARA CLOUD RUN
        
        # Rate limiting
        self.message_counts = defaultdict(list)
        self.max_messages_per_minute = 15  # ✅ AUMENTADO DE 10 PARA 15
        
        # Session locks para evitar race conditions
        self.session_locks = defaultdict(asyncio.Lock)
        
        # Gemini availability tracking
        self.gemini_available = True
        self.last_gemini_check = datetime.now()
        self.gemini_check_interval = timedelta(minutes=3)  # ✅ REDUZIDO DE 5min PARA 3min
        
        # ✅ CACHE EM MEMÓRIA PARA REDUZIR FIREBASE CALLS
        self.flow_cache = None
        self.flow_cache_time = None
        self.cache_ttl = 300  # 5 minutos
        
        logger.info("🚀 IntelligentHybridOrchestrator - CLOUD RUN ULTRA OTIMIZADO")
        logger.info(f"⚡ Timeouts: Gemini={self.gemini_timeout}s, Firebase={self.firebase_timeout}s")

    def safe_get_lead_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR QUE LEAD_DATA SEMPRE SEJA UM DICT VÁLIDO
        """
        lead_data = session_data.get("lead_data")
        if not lead_data or not isinstance(lead_data, dict):
            return {}
        return lead_data

    async def _get_cached_flow(self) -> Dict[str, Any]:
        """
        ✅ CACHE DE FLUXO PARA REDUZIR CALLS FIREBASE
        """
        now = datetime.now()
        
        # ✅ USAR CACHE SE VÁLIDO
        if (self.flow_cache and self.flow_cache_time and 
            (now - self.flow_cache_time).total_seconds() < self.cache_ttl):
            return self.flow_cache
        
        # ✅ BUSCAR NOVO FLUXO COM TIMEOUT AGRESSIVO
        try:
            flow = await asyncio.wait_for(
                get_conversation_flow(),
                timeout=self.firebase_timeout
            )
            self.flow_cache = flow
            self.flow_cache_time = now
            return flow
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Cache flow timeout ({self.firebase_timeout}s) - usando fallback")
            # ✅ FALLBACK INSTANTÂNEO
            fallback_flow = {
                "steps": [
                    {"id": 1, "question": "Qual é o seu nome completo?"},
                    {"id": 2, "question": "Qual o seu telefone e e-mail?"},
                    {"id": 3, "question": "Em qual área você precisa de ajuda? (Penal ou Saúde)"},
                    {"id": 4, "question": "Descreva sua situação:"},
                    {"id": 5, "question": "Posso direcioná-lo para nosso especialista?"}
                ],
                "completion_message": "Perfeito! Nossa equipe entrará em contato."
            }
            self.flow_cache = fallback_flow
            self.flow_cache_time = now
            return fallback_flow

    async def _ensure_session_integrity_fast(self, session_id: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR INTEGRIDADE DA SESSÃO - VERSÃO RÁPIDA
        """
        needs_save = False
        
        # ✅ GARANTIR LEAD_DATA SEMPRE PRESENTE
        if "lead_data" not in session_data or session_data["lead_data"] is None:
            session_data["lead_data"] = {}
            needs_save = True
        
        # ✅ GARANTIR CAMPOS ESSENCIAIS (MÍNIMOS)
        essential_fields = {
            "session_id": session_id,
            "current_step": 1,
            "flow_completed": False,
            "phone_submitted": False,
            "message_count": 0
        }
        
        for field, default_value in essential_fields.items():
            if field not in session_data:
                session_data[field] = default_value
                needs_save = True
        
        # ✅ SALVAR APENAS SE NECESSÁRIO E SEM BLOQUEAR
        if needs_save:
            # ✅ FIRE-AND-FORGET SAVE (NÃO BLOQUEAR)
            asyncio.create_task(self._save_session_async(session_id, session_data))
        
        return session_data

    async def _save_session_async(self, session_id: str, session_data: Dict[str, Any]):
        """
        ✅ SALVAR SESSÃO DE FORMA ASSÍNCRONA SEM BLOQUEAR
        """
        try:
            await asyncio.wait_for(
                save_user_session(session_id, session_data),
                timeout=self.firebase_timeout
            )
        except Exception as e:
            logger.warning(f"⚠️ Async save failed: {str(e)}")

    async def start_conversation(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ✅ INICIAR CONVERSA - VERSÃO ULTRA RÁPIDA
        """
        correlation_id = str(uuid.uuid4())[:8]
        
        try:
            # ✅ GERAR SESSION_ID RÁPIDO
            if not session_id:
                session_id = f"web_{int(datetime.now().timestamp())}_{correlation_id}"
            
            # ✅ SAUDAÇÃO RÁPIDA (SEM TIMEZONE COMPLEXO)
            hour = datetime.now().hour
            if 5 <= hour < 12:
                greeting = "Bom dia"
            elif 12 <= hour < 18:
                greeting = "Boa tarde"
            else:
                greeting = "Boa noite"
            
            welcome_message = f"{greeting}! Seja bem-vindo ao m.lima. Para começar, qual é o seu nome completo?"
            
            # ✅ CRIAR SESSÃO MÍNIMA
            session_data = {
                "session_id": session_id,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "message_count": 0,
                "lead_data": {},
                "created_at": datetime.now().isoformat()
            }
            
            # ✅ SAVE ASSÍNCRONO (NÃO BLOQUEAR)
            asyncio.create_task(self._save_session_async(session_id, session_data))
            
            return {
                "session_id": session_id,
                "response": welcome_message,
                "response_type": "greeting_fast",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Start error: {str(e)}")
            
            return {
                "session_id": session_id or f"error_{correlation_id}",
                "response": "Olá! Para começar, qual é o seu nome completo?",
                "response_type": "greeting_fallback",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},
                "correlation_id": correlation_id
            }

    async def process_message(
        self, 
        message: str, 
        session_id: str, 
        phone_number: Optional[str] = None,
        platform: str = "web"
    ) -> Dict[str, Any]:
        """
        ✅ PROCESSAR MENSAGEM - VERSÃO ULTRA OTIMIZADA PARA CLOUD RUN
        """
        correlation_id = str(uuid.uuid4())[:8]
        start_time = datetime.now()
        
        try:
            logger.info(f"📨 [{correlation_id}] Processing: '{message[:30]}...' | Session: {session_id}")
            
            # ✅ TIMEOUT GLOBAL PARA TODO O REQUEST
            return await asyncio.wait_for(
                self._process_message_internal(message, session_id, phone_number, platform, correlation_id),
                timeout=self.total_request_timeout
            )
            
        except asyncio.TimeoutError:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error(f"⏰ [{correlation_id}] TIMEOUT GLOBAL ({elapsed:.1f}s) - CLOUD RUN LIMIT")
            
            # ✅ RESPOSTA INSTANTÂNEA DE TIMEOUT
            return {
                "session_id": session_id,
                "response": "Desculpe, vamos tentar novamente. Qual é o seu nome completo?",
                "response_type": "cloud_run_timeout",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "lead_data": {},
                "timeout_seconds": elapsed,
                "correlation_id": correlation_id
            }
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error(f"❌ [{correlation_id}] Critical error ({elapsed:.1f}s): {str(e)}")
            
            return {
                "session_id": session_id,
                "response": "Ocorreu um erro. Vamos começar novamente. Qual é o seu nome completo?",
                "response_type": "system_error_recovery",
                "error": str(e),
                "lead_data": {},
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "correlation_id": correlation_id
            }

    async def _process_message_internal(
        self, 
        message: str, 
        session_id: str, 
        phone_number: Optional[str],
        platform: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ PROCESSAMENTO INTERNO COM TIMEOUTS AGRESSIVOS
        """
        # ✅ RATE LIMITING RÁPIDO
        if self._is_rate_limited(session_id):
            return {
                "session_id": session_id,
                "response": "⏳ Muitas mensagens. Aguarde um momento...",
                "response_type": "rate_limited",
                "lead_data": {},
                "correlation_id": correlation_id
            }
        
        # ✅ OBTER SESSÃO COM TIMEOUT ULTRA AGRESSIVO
        try:
            session_data = await asyncio.wait_for(
                get_user_session(session_id),
                timeout=self.firebase_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏰ [{correlation_id}] Firebase timeout ({self.firebase_timeout}s)")
            session_data = None
        except Exception:
            session_data = None
        
        # ✅ SESSÃO PADRÃO SE NÃO EXISTIR
        if not session_data:
            session_data = {
                "session_id": session_id,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "message_count": 0,
                "lead_data": {}
            }
        
        # ✅ GARANTIR INTEGRIDADE RÁPIDA
        session_data = await self._ensure_session_integrity_fast(session_id, session_data)
        
        # ✅ VERIFICAR SE PRECISA COLETAR TELEFONE
        if session_data.get("flow_completed") and not session_data.get("phone_submitted"):
            return await self._handle_phone_collection_fast(session_data, message, correlation_id)
        
        # ✅ TENTAR GEMINI COM TIMEOUT ULTRA AGRESSIVO
        gemini_result = await self._attempt_gemini_ultra_fast(message, session_id, session_data, correlation_id)
        
        if gemini_result["success"]:
            # ✅ SUCESSO GEMINI
            result = {
                "session_id": session_id,
                "response": gemini_result["response"],
                "response_type": "ai_intelligent",
                "ai_mode": True,
                "gemini_available": True,
                "lead_data": self.safe_get_lead_data(session_data),
                "message_count": session_data.get("message_count", 0) + 1
            }
            
            # ✅ UPDATE ASSÍNCRONO
            session_data["message_count"] = result["message_count"]
            asyncio.create_task(self._save_session_async(session_id, session_data))
            
            return result
        
        # ✅ FALLBACK FIREBASE ULTRA RÁPIDO
        return await self._get_fallback_response_fast(session_data, message, correlation_id)

    async def _attempt_gemini_ultra_fast(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any],
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ GEMINI COM TIMEOUT ULTRA AGRESSIVO
        """
        try:
            logger.info(f"🤖 [{correlation_id}] Gemini attempt ({self.gemini_timeout}s)")
            
            response = await asyncio.wait_for(
                ai_orchestrator.generate_response(
                    message, 
                    session_id=session_id,
                    context={"platform": session_data.get("platform", "web")}
                ),
                timeout=self.gemini_timeout
            )
            
            if response and len(response.strip()) > 0:
                logger.info(f"✅ [{correlation_id}] Gemini success")
                self.gemini_available = True
                return {"success": True, "response": response}
            else:
                return {"success": False, "reason": "empty_response"}
                
        except asyncio.TimeoutError:
            logger.warning(f"⏰ [{correlation_id}] Gemini timeout ({self.gemini_timeout}s)")
            self.gemini_available = False
            return {"success": False, "reason": "timeout"}
        except Exception as e:
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["quota", "429", "billing"]):
                logger.warning(f"🚫 [{correlation_id}] Gemini quota")
                self.gemini_available = False
                return {"success": False, "reason": "quota_exceeded"}
            else:
                return {"success": False, "reason": "api_error"}

    async def _get_fallback_response_fast(
        self, 
        session_data: Dict[str, Any], 
        message: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ FALLBACK FIREBASE ULTRA RÁPIDO
        """
        try:
            session_id = session_data["session_id"]
            current_step = session_data.get("current_step", 1)
            lead_data = self.safe_get_lead_data(session_data)
            
            logger.info(f"🚀 [{correlation_id}] Fallback step {current_step}")
            
            # ✅ OBTER FLUXO DO CACHE
            flow = await self._get_cached_flow()
            steps = flow.get("steps", [])
            
            # ✅ VALIDAR E AVANÇAR
            if current_step <= len(steps):
                # ✅ SALVAR RESPOSTA
                lead_data[f"step_{current_step}"] = message.strip()
                next_step = current_step + 1
                
                if next_step <= len(steps):
                    # ✅ PRÓXIMA PERGUNTA
                    next_question_data = next((s for s in steps if s["id"] == next_step), None)
                    if next_question_data:
                        next_question = next_question_data["question"]
                        
                        # ✅ PERSONALIZAR COM NOME
                        if "{user_name}" in next_question and "step_1" in lead_data:
                            user_name = lead_data["step_1"].split()[0]
                            next_question = next_question.replace("{user_name}", user_name)
                        
                        # ✅ ATUALIZAR SESSÃO
                        session_data["current_step"] = next_step
                        session_data["lead_data"] = lead_data
                        session_data["message_count"] = session_data.get("message_count", 0) + 1
                        
                        # ✅ SAVE ASSÍNCRONO
                        asyncio.create_task(self._save_session_async(session_id, session_data))
                        
                        return {
                            "session_id": session_id,
                            "response": next_question,
                            "response_type": "fallback_firebase",
                            "current_step": next_step,
                            "flow_completed": False,
                            "ai_mode": False,
                            "lead_data": lead_data,
                            "message_count": session_data["message_count"]
                        }
                
                # ✅ FLUXO COMPLETO
                logger.info(f"🎯 [{correlation_id}] Flow complete - collect phone")
                
                session_data["flow_completed"] = True
                session_data["lead_data"] = lead_data
                
                # ✅ SAVE ASSÍNCRONO
                asyncio.create_task(self._save_session_async(session_id, session_data))
                
                completion_message = flow.get("completion_message", "Perfeito! Para finalizar, preciso do seu WhatsApp:")
                
                if "{user_name}" in completion_message and "step_1" in lead_data:
                    user_name = lead_data["step_1"].split()[0]
                    completion_message = completion_message.replace("{user_name}", user_name)
                
                return {
                    "session_id": session_id,
                    "response": f"{completion_message}\n\nPor favor, informe seu WhatsApp:",
                    "response_type": "flow_completed_collect_phone",
                    "flow_completed": True,
                    "collecting_phone": True,
                    "ai_mode": False,
                    "lead_data": lead_data,
                    "message_count": session_data.get("message_count", 0) + 1
                }
            
            # ✅ FALLBACK GENÉRICO
            return {
                "session_id": session_id,
                "response": "Qual é o seu nome completo?",
                "response_type": "fallback_generic",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "lead_data": lead_data
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Fallback error: {str(e)}")
            
            return {
                "session_id": session_data.get("session_id", "error"),
                "response": "Qual é o seu nome completo?",
                "response_type": "fallback_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "lead_data": {},
                "error": str(e)
            }

    async def _handle_phone_collection_fast(
        self, 
        session_data: Dict[str, Any], 
        phone_message: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ COLETAR TELEFONE ULTRA RÁPIDO
        """
        try:
            session_id = session_data["session_id"]
            lead_data = self.safe_get_lead_data(session_data)
            
            logger.info(f"📱 [{correlation_id}] Phone collection")
            
            # ✅ VALIDAR TELEFONE
            if self._is_phone_number(phone_message):
                clean_phone = self._format_brazilian_phone(phone_message)
                
                # ✅ SALVAR TELEFONE
                lead_data["phone"] = clean_phone
                session_data["phone_submitted"] = True
                session_data["lead_data"] = lead_data
                
                # ✅ PROCESSOS ASSÍNCRONOS (NÃO BLOQUEAR)
                asyncio.create_task(self._save_lead_async(lead_data, correlation_id))
                asyncio.create_task(self._save_session_async(session_id, session_data))
                asyncio.create_task(self._send_whatsapp_async(lead_data, clean_phone, correlation_id))
                asyncio.create_task(self._notify_lawyers_async(lead_data, correlation_id))
                
                return {
                    "session_id": session_id,
                    "response": f"✅ Telefone {clean_phone} confirmado!\n\nObrigado! Nossa equipe entrará em contato em breve via WhatsApp.",
                    "response_type": "phone_collected_fast",
                    "flow_completed": True,
                    "phone_submitted": True,
                    "phone_number": clean_phone,
                    "lead_saved": True,
                    "whatsapp_sent": True,
                    "lawyers_notified": True,
                    "lead_data": lead_data
                }
            else:
                return {
                    "session_id": session_id,
                    "response": "Por favor, informe um WhatsApp válido (com DDD):\n\nExemplo: 11999999999",
                    "response_type": "phone_validation_error",
                    "flow_completed": True,
                    "collecting_phone": True,
                    "validation_error": True,
                    "lead_data": lead_data
                }
                
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Phone collection error: {str(e)}")
            
            return {
                "session_id": session_data.get("session_id", "error"),
                "response": "Ocorreu um erro. Por favor, informe seu WhatsApp novamente:",
                "response_type": "phone_collection_error",
                "flow_completed": True,
                "collecting_phone": True,
                "error": str(e),
                "lead_data": self.safe_get_lead_data(session_data)
            }

    async def _save_lead_async(self, lead_data: Dict[str, Any], correlation_id: str):
        """✅ SALVAR LEAD ASSÍNCRONO"""
        try:
            await asyncio.wait_for(
                save_lead_data({"answers": lead_data}),
                timeout=self.firebase_timeout
            )
            logger.info(f"💾 [{correlation_id}] Lead saved async")
        except Exception as e:
            logger.warning(f"❌ [{correlation_id}] Lead save failed: {str(e)}")

    async def _send_whatsapp_async(self, lead_data: Dict[str, Any], phone: str, correlation_id: str):
        """✅ ENVIAR WHATSAPP ASSÍNCRONO"""
        try:
            user_name = lead_data.get("step_1", "Cliente")
            user_message = f"Olá {user_name}! 👋\n\nObrigado por entrar em contato com o m.lima.\n\nEm breve entraremos em contato. 📞"
            
            await asyncio.wait_for(
                baileys_service.send_whatsapp_message(phone, user_message),
                timeout=self.whatsapp_timeout
            )
            logger.info(f"📤 [{correlation_id}] WhatsApp sent async")
        except Exception as e:
            logger.warning(f"❌ [{correlation_id}] WhatsApp failed: {str(e)}")

    async def _notify_lawyers_async(self, lead_data: Dict[str, Any], correlation_id: str):
        """✅ NOTIFICAR ADVOGADOS ASSÍNCRONO"""
        try:
            user_name = lead_data.get("step_1", "Cliente")
            phone = lead_data.get("phone", "")
            area = lead_data.get("step_3", "")
            
            await asyncio.wait_for(
                lawyer_notification_service.notify_lawyers_of_new_lead(
                    lead_name=user_name,
                    lead_phone=phone,
                    category=area,
                    additional_info=lead_data
                ),
                timeout=self.notification_timeout
            )
            logger.info(f"👨‍⚖️ [{correlation_id}] Lawyers notified async")
        except Exception as e:
            logger.warning(f"❌ [{correlation_id}] Lawyer notification failed: {str(e)}")

    def _is_rate_limited(self, session_id: str) -> bool:
        """Rate limiting otimizado."""
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)
        
        # ✅ LIMPEZA RÁPIDA
        self.message_counts[session_id] = [
            msg_time for msg_time in self.message_counts[session_id] 
            if msg_time > cutoff
        ]
        
        if len(self.message_counts[session_id]) >= self.max_messages_per_minute:
            return True
        
        self.message_counts[session_id].append(now)
        return False

    def _is_phone_number(self, text: str) -> bool:
        """Validação rápida de telefone."""
        clean = re.sub(r'[^\d]', '', text)
        return 10 <= len(clean) <= 13

    def _format_brazilian_phone(self, phone: str) -> str:
        """Formatação rápida de telefone."""
        clean = re.sub(r'[^\d]', '', phone)
        if not clean.startswith("55"):
            clean = f"55{clean}"
        return clean

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        ✅ OBTER CONTEXTO ULTRA RÁPIDO
        """
        try:
            session_data = await asyncio.wait_for(
                get_user_session(session_id),
                timeout=self.firebase_timeout
            )
            
            if not session_data:
                return {
                    "session_id": session_id,
                    "status_info": {"step": 1, "flow_completed": False, "phone_submitted": False, "state": "not_found"},
                    "lead_data": {},
                    "current_step": 1,
                    "flow_completed": False,
                    "phone_submitted": False
                }
            
            return {
                "session_id": session_id,
                "status_info": {
                    "step": session_data.get("current_step", 1),
                    "flow_completed": session_data.get("flow_completed", False),
                    "phone_submitted": session_data.get("phone_submitted", False),
                    "state": "active"
                },
                "lead_data": self.safe_get_lead_data(session_data),
                "current_step": session_data.get("current_step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "message_count": session_data.get("message_count", 0)
            }
            
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Context timeout for {session_id}")
            return {
                "session_id": session_id,
                "status_info": {"step": 1, "flow_completed": False, "phone_submitted": False, "state": "timeout"},
                "lead_data": {},
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False
            }
        except Exception as e:
            logger.error(f"❌ Context error {session_id}: {str(e)}")
            return {
                "session_id": session_id,
                "status_info": {"step": 1, "flow_completed": False, "phone_submitted": False, "state": "error"},
                "lead_data": {},
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "error": str(e)
            }

    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Status otimizado."""
        try:
            return {
                "overall_status": "active",
                "ai_status": "active" if self.gemini_available else "quota_exceeded",
                "gemini_available": self.gemini_available,
                "fallback_mode": not self.gemini_available,
                "cloud_run_optimized": True,
                "timeouts": {
                    "gemini": f"{self.gemini_timeout}s",
                    "firebase": f"{self.firebase_timeout}s",
                    "whatsapp": f"{self.whatsapp_timeout}s",
                    "total_request": f"{self.total_request_timeout}s"
                },
                "features": [
                    "ultra_aggressive_timeouts",
                    "async_processing",
                    "flow_caching",
                    "cloud_run_optimized",
                    "fire_and_forget_saves"
                ]
            }
        except Exception as e:
            return {"overall_status": "degraded", "error": str(e), "fallback_mode": True}

    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]):
        """Handle WhatsApp authorization."""
        try:
            logger.info(f"🔐 WhatsApp auth: {auth_data.get('session_id')}")
            return {"status": "authorized"}
        except Exception as e:
            logger.error(f"❌ WhatsApp auth error: {str(e)}")
            return {"status": "error", "error": str(e)}


# ✅ INSTÂNCIA GLOBAL
intelligent_orchestrator = IntelligentHybridOrchestrator()

logger.info("🚀 IntelligentHybridOrchestrator - CLOUD RUN ULTRA OTIMIZADO CARREGADO")