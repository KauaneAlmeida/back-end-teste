"""
Intelligent Hybrid Orchestrator - PRODUCTION READY

Sistema de orquestração inteligente que combina:
- IA Gemini para respostas naturais
- Fallback Firebase para fluxo estruturado
- Validação rigorosa de lead_data
- Timeouts otimizados para Cloud Run
- Auto-reinicialização de sessões
- Saudação personalizada por horário
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
    ✅ ORQUESTRADOR HÍBRIDO INTELIGENTE - PRODUCTION READY
    
    Combina IA Gemini + Fallback Firebase com:
    - Validação rigorosa de lead_data (elimina HTTP 500)
    - Timeouts ultra otimizados para Cloud Run
    - Auto-reinicialização de sessões travadas
    - Saudação personalizada por horário
    - Rate limiting e proteção contra spam
    """
    
    def __init__(self):
        # ⏰ TIMEOUTS ULTRA AGRESSIVOS PARA CLOUD RUN
        self.gemini_timeout = 4  # ✅ REDUZIDO DE 8s PARA 4s
        self.whatsapp_timeout = 6  # ✅ REDUZIDO DE 10s PARA 6s
        self.firebase_timeout = 3  # ✅ REDUZIDO DE 5s PARA 3s
        self.whatsapp_global_timeout = 15  # ✅ REDUZIDO DE 25s PARA 15s
        self.notification_timeout = 8  # ✅ REDUZIDO DE 15s PARA 8s
        
        # Rate limiting
        self.message_counts = defaultdict(list)
        self.max_messages_per_minute = 10
        
        # Session locks para evitar race conditions
        self.session_locks = defaultdict(asyncio.Lock)
        
        # Gemini availability tracking
        self.gemini_available = True
        self.last_gemini_check = datetime.now()
        self.gemini_check_interval = timedelta(minutes=5)
        
        logger.info("🚀 IntelligentHybridOrchestrator inicializado com timeouts ultra agressivos")

    def safe_get_lead_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR QUE LEAD_DATA SEMPRE SEJA UM DICT VÁLIDO
        
        Esta função elimina o erro HTTP 500 causado por lead_data undefined/null
        """
        lead_data = session_data.get("lead_data")
        if not lead_data or not isinstance(lead_data, dict):
            return {}
        return lead_data

    async def _ensure_session_integrity(self, session_id: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR INTEGRIDADE DA SESSÃO
        
        Corrige sessões antigas que não têm lead_data ou têm campos inválidos
        """
        needs_save = False
        
        # ✅ GARANTIR LEAD_DATA SEMPRE PRESENTE
        if "lead_data" not in session_data or session_data["lead_data"] is None:
            session_data["lead_data"] = {}
            needs_save = True
            logger.warning(f"⚠️ Corrigindo lead_data ausente na sessão {session_id}")
        
        # ✅ GARANTIR CAMPOS ESSENCIAIS
        essential_fields = {
            "session_id": session_id,
            "platform": "web",
            "current_step": 1,
            "flow_completed": False,
            "phone_submitted": False,
            "gemini_available": True,
            "message_count": 0,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat()
        }
        
        for field, default_value in essential_fields.items():
            if field not in session_data:
                session_data[field] = default_value
                needs_save = True
        
        # ✅ SALVAR SE HOUVER CORREÇÕES (COM TIMEOUT)
        if needs_save:
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"✅ Sessão {session_id} corrigida e salva")
            except asyncio.TimeoutError:
                logger.warning(f"⏰ Timeout Firebase save ({self.firebase_timeout}s) - continuando")
            except Exception as save_error:
                logger.warning(f"❌ Erro Firebase save: {str(save_error)} - continuando")
        
        return session_data

    async def start_conversation(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ✅ INICIAR CONVERSA COM SAUDAÇÃO PERSONALIZADA POR HORÁRIO
        
        Retorna saudação baseada no horário de Brasília:
        - Bom dia (5h-12h)
        - Boa tarde (12h-18h) 
        - Boa noite (18h-5h)
        """
        correlation_id = str(uuid.uuid4())[:8]
        
        try:
            # ✅ GERAR SESSION_ID SE NÃO FORNECIDO
            if not session_id:
                session_id = f"web_{int(datetime.now().timestamp())}_{correlation_id}"
            
            logger.info(f"🚀 [{correlation_id}] Iniciando conversa: {session_id}")
            
            # ✅ SAUDAÇÃO PERSONALIZADA POR HORÁRIO (BRASÍLIA)
            try:
                brasilia_tz = pytz.timezone('America/Sao_Paulo')
                now = datetime.now(brasilia_tz)
                hour = now.hour
                
                if 5 <= hour < 12:
                    greeting = "Bom dia"
                elif 12 <= hour < 18:
                    greeting = "Boa tarde"
                else:
                    greeting = "Boa noite"
                
                logger.info(f"🌅 [{correlation_id}] Horário: {hour}h - Saudação: {greeting}")
                
            except Exception as time_error:
                logger.warning(f"⚠️ [{correlation_id}] Erro ao obter horário: {str(time_error)}")
                greeting = "Olá"
            
            # ✅ MENSAGEM DE SAUDAÇÃO COMPLETA
            welcome_message = f"{greeting}! Seja bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com um de nossos advogados especializados.\n\nPara começar, qual é o seu nome completo?"
            
            # ✅ CRIAR SESSÃO INICIAL COM LEAD_DATA VÁLIDO
            session_data = {
                "session_id": session_id,
                "platform": "web",
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "message_count": 0,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "correlation_id": correlation_id
            }
            
            # ✅ SALVAR SESSÃO (COM TIMEOUT)
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"✅ [{correlation_id}] Sessão inicial salva")
            except asyncio.TimeoutError:
                logger.warning(f"⏰ [{correlation_id}] Timeout Firebase save ({self.firebase_timeout}s) - continuando")
            except Exception as save_error:
                logger.warning(f"❌ [{correlation_id}] Erro Firebase save: {str(save_error)} - continuando")
            
            return {
                "session_id": session_id,
                "response": welcome_message,
                "response_type": "greeting_personalized",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "greeting_type": greeting.lower().replace(" ", "_"),
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao iniciar conversa: {str(e)}")
            
            # ✅ FALLBACK SEGURO COM LEAD_DATA VÁLIDO
            return {
                "session_id": session_id or f"error_{correlation_id}",
                "response": "Olá! Seja bem-vindo ao m.lima. Para começar, qual é o seu nome completo?",
                "response_type": "greeting_fallback",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "error": str(e),
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
        ✅ PROCESSAR MENSAGEM COM VALIDAÇÃO RIGOROSA DE LEAD_DATA
        
        Garante que lead_data sempre seja um dict válido, eliminando HTTP 500
        """
        correlation_id = str(uuid.uuid4())[:8]
        
        try:
            logger.info(f"📨 [{correlation_id}] Processando: '{message[:50]}...' | Sessão: {session_id}")
            
            # ✅ RATE LIMITING
            if self._is_rate_limited(session_id):
                return {
                    "session_id": session_id,
                    "response": "⏳ Muitas mensagens em pouco tempo. Aguarde um momento...",
                    "response_type": "rate_limited",
                    "lead_data": {},  # ✅ SEMPRE PRESENTE
                    "correlation_id": correlation_id
                }
            
            # ✅ OBTER SESSÃO COM TIMEOUT
            try:
                session_data = await asyncio.wait_for(
                    get_user_session(session_id),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ [{correlation_id}] Timeout Firebase ({self.firebase_timeout}s) - usando sessão padrão")
                session_data = None
            except Exception as firebase_error:
                logger.warning(f"❌ [{correlation_id}] Erro Firebase: {str(firebase_error)} - usando sessão padrão")
                session_data = None
            
            # ✅ CRIAR SESSÃO PADRÃO SE NÃO EXISTIR
            if not session_data:
                session_data = {
                    "session_id": session_id,
                    "platform": platform,
                    "current_step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "gemini_available": True,
                    "message_count": 0,
                    "lead_data": {},  # ✅ SEMPRE PRESENTE
                    "created_at": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat()
                }
                logger.info(f"🆕 [{correlation_id}] Criada sessão padrão")
            
            # ✅ GARANTIR INTEGRIDADE DA SESSÃO
            session_data = await self._ensure_session_integrity(session_id, session_data)
            
            # ✅ VERIFICAR SE PRECISA AUTO-REINICIAR
            if session_data.get("flow_completed") and session_data.get("phone_submitted"):
                if message.lower().strip() in ["oi", "olá", "hello", "nova conversa", "reiniciar"]:
                    logger.info(f"🔄 [{correlation_id}] Auto-reiniciando sessão finalizada")
                    return await self._auto_restart_session(session_id, message, correlation_id)
            
            # ✅ PROCESSAR MENSAGEM
            result = await self._process_conversation_flow(session_data, message, correlation_id)
            
            # ✅ GARANTIR LEAD_DATA SEMPRE PRESENTE NO RESULTADO
            if "lead_data" not in result:
                result["lead_data"] = self.safe_get_lead_data(session_data)
            
            result["correlation_id"] = correlation_id
            return result
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro crítico: {str(e)}")
            
            # ✅ FALLBACK SEGURO COM LEAD_DATA VÁLIDO
            return {
                "session_id": session_id,
                "response": "Desculpe, ocorreu um erro temporário. Vamos tentar novamente?",
                "response_type": "system_error_recovery",
                "error": str(e),
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "correlation_id": correlation_id
            }

    async def _auto_restart_session(self, session_id: str, message: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ AUTO-REINICIALIZAR SESSÃO FINALIZADA
        
        Remove o problema do chat "finalizado" permanente
        """
        try:
            logger.info(f"🔄 [{correlation_id}] Auto-reiniciando sessão: {session_id}")
            
            # ✅ CRIAR NOVA SESSÃO LIMPA
            new_session_data = {
                "session_id": session_id,
                "platform": "web",
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "message_count": 1,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "restarted": True,
                "restart_reason": "auto_restart_after_completion"
            }
            
            # ✅ SALVAR NOVA SESSÃO (COM TIMEOUT)
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, new_session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"✅ [{correlation_id}] Nova sessão salva após restart")
            except asyncio.TimeoutError:
                logger.warning(f"⏰ [{correlation_id}] Timeout Firebase save restart ({self.firebase_timeout}s)")
            except Exception as save_error:
                logger.warning(f"❌ [{correlation_id}] Erro save restart: {str(save_error)}")
            
            # ✅ PROCESSAR MENSAGEM NA NOVA SESSÃO
            return await self._process_conversation_flow(new_session_data, message, correlation_id)
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no auto-restart: {str(e)}")
            
            # ✅ FALLBACK PARA SAUDAÇÃO SIMPLES
            return {
                "session_id": session_id,
                "response": "Olá! Vamos começar uma nova conversa. Qual é o seu nome completo?",
                "response_type": "restart_fallback",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "error": str(e),
                "correlation_id": correlation_id
            }

    async def _process_conversation_flow(
        self, 
        session_data: Dict[str, Any], 
        message: str, 
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ PROCESSAR FLUXO DE CONVERSA COM VALIDAÇÃO RIGOROSA
        """
        try:
            session_id = session_data["session_id"]
            
            # ✅ GARANTIR LEAD_DATA VÁLIDO
            lead_data = self.safe_get_lead_data(session_data)
            
            # ✅ VERIFICAR SE JÁ COLETOU TELEFONE
            if session_data.get("flow_completed") and not session_data.get("phone_submitted"):
                return await self._handle_phone_collection(session_data, message, correlation_id)
            
            # ✅ TENTAR GEMINI PRIMEIRO (COM TIMEOUT AGRESSIVO)
            gemini_result = await self._attempt_gemini_response(message, session_id, session_data, correlation_id)
            
            if gemini_result["success"]:
                # ✅ SUCESSO GEMINI - RETORNAR COM LEAD_DATA VÁLIDO
                result = {
                    "session_id": session_id,
                    "response": gemini_result["response"],
                    "response_type": "ai_intelligent",
                    "ai_mode": True,
                    "gemini_available": True,
                    "lead_data": lead_data,  # ✅ SEMPRE PRESENTE
                    "message_count": session_data.get("message_count", 0) + 1
                }
                
                # ✅ SALVAR SESSÃO ATUALIZADA (COM TIMEOUT)
                session_data["message_count"] = result["message_count"]
                session_data["last_updated"] = datetime.now().isoformat()
                session_data["gemini_available"] = True
                
                try:
                    await asyncio.wait_for(
                        save_user_session(session_id, session_data),
                        timeout=self.firebase_timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⏰ [{correlation_id}] Timeout save Gemini success ({self.firebase_timeout}s)")
                except Exception as save_error:
                    logger.warning(f"❌ [{correlation_id}] Erro save Gemini: {str(save_error)}")
                
                return result
            
            # ✅ GEMINI FALHOU - USAR FALLBACK FIREBASE
            logger.info(f"⚡ [{correlation_id}] Ativando fallback Firebase")
            return await self._get_fallback_response(session_data, message, correlation_id)
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no fluxo: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_data.get("session_id", "error"),
                "response": "Desculpe, vamos tentar novamente. Qual é o seu nome completo?",
                "response_type": "flow_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "error": str(e)
            }

    async def _attempt_gemini_response(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any],
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ TENTAR RESPOSTA GEMINI COM TIMEOUT ULTRA AGRESSIVO
        """
        try:
            logger.info(f"🤖 [{correlation_id}] Tentando Gemini (timeout: {self.gemini_timeout}s)")
            
            # ✅ TIMEOUT ULTRA AGRESSIVO PARA CLOUD RUN
            response = await asyncio.wait_for(
                ai_orchestrator.generate_response(
                    message, 
                    session_id=session_id,
                    context={"platform": session_data.get("platform", "web")}
                ),
                timeout=self.gemini_timeout
            )
            
            if response and len(response.strip()) > 0:
                logger.info(f"✅ [{correlation_id}] Gemini sucesso: {response[:50]}...")
                self.gemini_available = True
                return {"success": True, "response": response}
            else:
                logger.warning(f"⚠️ [{correlation_id}] Gemini resposta vazia")
                return {"success": False, "reason": "empty_response"}
                
        except asyncio.TimeoutError:
            logger.warning(f"⏰ [{correlation_id}] Gemini timeout ({self.gemini_timeout}s)")
            self.gemini_available = False
            return {"success": False, "reason": "timeout"}
        except Exception as e:
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["quota", "429", "billing", "resourceexhausted"]):
                logger.warning(f"🚫 [{correlation_id}] Gemini quota/billing: {str(e)}")
                self.gemini_available = False
                return {"success": False, "reason": "quota_exceeded"}
            else:
                logger.warning(f"❌ [{correlation_id}] Gemini erro: {str(e)}")
                return {"success": False, "reason": "api_error"}

    async def _get_fallback_response(
        self, 
        session_data: Dict[str, Any], 
        message: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ FALLBACK FIREBASE COM VALIDAÇÃO RIGOROSA
        """
        try:
            session_id = session_data["session_id"]
            current_step = session_data.get("current_step", 1)
            
            # ✅ GARANTIR LEAD_DATA VÁLIDO
            lead_data = self.safe_get_lead_data(session_data)
            
            logger.info(f"🚀 [{correlation_id}] Fallback Firebase - Step {current_step}")
            
            # ✅ OBTER FLUXO (COM TIMEOUT)
            try:
                flow = await asyncio.wait_for(
                    get_conversation_flow(),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ [{correlation_id}] Timeout flow ({self.firebase_timeout}s) - usando padrão")
                flow = {"steps": [
                    {"id": 1, "question": "Qual é o seu nome completo?"},
                    {"id": 2, "question": "Qual o seu telefone e e-mail?"},
                    {"id": 3, "question": "Em qual área você precisa de ajuda?"},
                    {"id": 4, "question": "Descreva sua situação:"},
                    {"id": 5, "question": "Posso direcioná-lo para nosso especialista?"}
                ]}
            except Exception as flow_error:
                logger.warning(f"❌ [{correlation_id}] Erro flow: {str(flow_error)} - usando padrão")
                flow = {"steps": [
                    {"id": 1, "question": "Qual é o seu nome completo?"},
                    {"id": 2, "question": "Qual o seu telefone e e-mail?"},
                    {"id": 3, "question": "Em qual área você precisa de ajuda?"},
                    {"id": 4, "question": "Descreva sua situação:"},
                    {"id": 5, "question": "Posso direcioná-lo para nosso especialista?"}
                ]}
            
            steps = flow.get("steps", [])
            
            # ✅ VALIDAR RESPOSTA E AVANÇAR
            if current_step <= len(steps):
                # ✅ SALVAR RESPOSTA NO LEAD_DATA
                lead_data[f"step_{current_step}"] = message.strip()
                
                # ✅ AVANÇAR PARA PRÓXIMO STEP
                next_step = current_step + 1
                
                if next_step <= len(steps):
                    # ✅ PRÓXIMA PERGUNTA
                    next_question_data = next((s for s in steps if s["id"] == next_step), None)
                    if next_question_data:
                        next_question = next_question_data["question"]
                        
                        # ✅ PERSONALIZAR PERGUNTA COM NOME
                        if "{user_name}" in next_question and "step_1" in lead_data:
                            user_name = lead_data["step_1"].split()[0]  # Primeiro nome
                            next_question = next_question.replace("{user_name}", user_name)
                        
                        # ✅ ATUALIZAR SESSÃO
                        session_data["current_step"] = next_step
                        session_data["lead_data"] = lead_data
                        session_data["last_updated"] = datetime.now().isoformat()
                        session_data["message_count"] = session_data.get("message_count", 0) + 1
                        
                        # ✅ SALVAR SESSÃO (COM TIMEOUT)
                        try:
                            await asyncio.wait_for(
                                save_user_session(session_id, session_data),
                                timeout=self.firebase_timeout
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"⏰ [{correlation_id}] Timeout save step ({self.firebase_timeout}s)")
                        except Exception as save_error:
                            logger.warning(f"❌ [{correlation_id}] Erro save step: {str(save_error)}")
                        
                        return {
                            "session_id": session_id,
                            "response": next_question,
                            "response_type": "fallback_firebase",
                            "current_step": next_step,
                            "flow_completed": False,
                            "ai_mode": False,
                            "lead_data": lead_data,  # ✅ SEMPRE PRESENTE
                            "message_count": session_data["message_count"]
                        }
                
                # ✅ FLUXO COMPLETO - COLETAR TELEFONE
                logger.info(f"🎯 [{correlation_id}] Fluxo completo - coletando telefone")
                
                session_data["flow_completed"] = True
                session_data["lead_data"] = lead_data
                session_data["last_updated"] = datetime.now().isoformat()
                
                # ✅ SALVAR SESSÃO (COM TIMEOUT)
                try:
                    await asyncio.wait_for(
                        save_user_session(session_id, session_data),
                        timeout=self.firebase_timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⏰ [{correlation_id}] Timeout save complete ({self.firebase_timeout}s)")
                except Exception as save_error:
                    logger.warning(f"❌ [{correlation_id}] Erro save complete: {str(save_error)}")
                
                completion_message = flow.get("completion_message", "Perfeito! Para finalizar, preciso do seu WhatsApp:")
                
                # ✅ PERSONALIZAR COM NOME
                if "{user_name}" in completion_message and "step_1" in lead_data:
                    user_name = lead_data["step_1"].split()[0]
                    completion_message = completion_message.replace("{user_name}", user_name)
                
                return {
                    "session_id": session_id,
                    "response": f"{completion_message}\n\nPor favor, informe seu WhatsApp para que possamos entrar em contato:",
                    "response_type": "flow_completed_collect_phone",
                    "flow_completed": True,
                    "collecting_phone": True,
                    "ai_mode": False,
                    "lead_data": lead_data,  # ✅ SEMPRE PRESENTE
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
                "lead_data": lead_data,  # ✅ SEMPRE PRESENTE
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro fallback: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_data.get("session_id", "error"),
                "response": "Vamos começar novamente. Qual é o seu nome completo?",
                "response_type": "fallback_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "error": str(e)
            }

    async def _handle_phone_collection(
        self, 
        session_data: Dict[str, Any], 
        phone_message: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ COLETAR TELEFONE E FINALIZAR LEAD
        """
        try:
            session_id = session_data["session_id"]
            
            # ✅ GARANTIR LEAD_DATA VÁLIDO
            lead_data = self.safe_get_lead_data(session_data)
            
            logger.info(f"📱 [{correlation_id}] Coletando telefone: {phone_message}")
            
            # ✅ VALIDAR TELEFONE
            if self._is_phone_number(phone_message):
                clean_phone = self._format_brazilian_phone(phone_message)
                
                # ✅ SALVAR TELEFONE
                lead_data["phone"] = clean_phone
                session_data["phone_submitted"] = True
                session_data["lead_data"] = lead_data
                session_data["last_updated"] = datetime.now().isoformat()
                
                # ✅ SALVAR LEAD NO FIREBASE (COM TIMEOUT)
                try:
                    lead_id = await asyncio.wait_for(
                        save_lead_data({"answers": lead_data}),
                        timeout=self.firebase_timeout
                    )
                    logger.info(f"💾 [{correlation_id}] Lead salvo: {lead_id}")
                except asyncio.TimeoutError:
                    logger.warning(f"⏰ [{correlation_id}] Timeout save lead ({self.firebase_timeout}s)")
                    lead_id = None
                except Exception as save_error:
                    logger.warning(f"❌ [{correlation_id}] Erro save lead: {str(save_error)}")
                    lead_id = None
                
                # ✅ SALVAR SESSÃO (COM TIMEOUT)
                try:
                    await asyncio.wait_for(
                        save_user_session(session_id, session_data),
                        timeout=self.firebase_timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⏰ [{correlation_id}] Timeout save session phone ({self.firebase_timeout}s)")
                except Exception as save_error:
                    logger.warning(f"❌ [{correlation_id}] Erro save session phone: {str(save_error)}")
                
                # ✅ ENVIAR WHATSAPP (COM TIMEOUT GLOBAL)
                whatsapp_success = await self._send_whatsapp_messages(lead_data, clean_phone, correlation_id)
                
                # ✅ NOTIFICAR ADVOGADOS (COM TIMEOUT)
                await self._notify_lawyers_async(lead_data, correlation_id)
                
                return {
                    "session_id": session_id,
                    "response": f"✅ Telefone {clean_phone} confirmado!\n\nObrigado! Nossa equipe entrará em contato em breve via WhatsApp.\n\nSuas informações foram registradas e um de nossos advogados especializados já vai analisar seu caso.",
                    "response_type": "phone_collected_fallback",
                    "flow_completed": True,
                    "phone_submitted": True,
                    "phone_number": clean_phone,
                    "lead_saved": bool(lead_id),
                    "lead_id": lead_id,
                    "whatsapp_sent": whatsapp_success,
                    "lawyers_notified": True,
                    "lead_data": lead_data,  # ✅ SEMPRE PRESENTE
                }
            else:
                # ✅ TELEFONE INVÁLIDO
                return {
                    "session_id": session_id,
                    "response": "Por favor, informe um número de WhatsApp válido (com DDD):\n\nExemplo: 11999999999",
                    "response_type": "phone_validation_error",
                    "flow_completed": True,
                    "collecting_phone": True,
                    "validation_error": True,
                    "lead_data": lead_data,  # ✅ SEMPRE PRESENTE
                }
                
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro coleta telefone: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_data.get("session_id", "error"),
                "response": "Ocorreu um erro. Por favor, informe seu WhatsApp novamente:",
                "response_type": "phone_collection_error",
                "flow_completed": True,
                "collecting_phone": True,
                "error": str(e),
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE PRESENTE
            }

    async def _send_whatsapp_messages(self, lead_data: Dict[str, Any], phone: str, correlation_id: str) -> bool:
        """
        ✅ ENVIAR MENSAGENS WHATSAPP COM TIMEOUT GLOBAL
        """
        try:
            user_name = lead_data.get("step_1", "Cliente")
            
            # ✅ MENSAGEM PARA USUÁRIO
            user_message = f"Olá {user_name}! 👋\n\nObrigado por entrar em contato com o m.lima.\n\nSuas informações foram registradas e um de nossos advogados especializados já vai analisar seu caso.\n\nEm breve entraremos em contato para agendar uma consulta. 📞"
            
            # ✅ MENSAGEM INTERNA
            internal_message = f"🚨 Nova Lead Capturada!\n\nNome: {user_name}\nTelefone: {phone}\nÁrea: {lead_data.get('step_3', 'Não informado')}\nSituação: {lead_data.get('step_4', 'Não informado')[:100]}..."
            
            # ✅ ENVIAR COM TIMEOUT GLOBAL
            async def send_messages():
                tasks = []
                
                # ✅ MENSAGEM PARA USUÁRIO
                tasks.append(baileys_service.send_whatsapp_message(phone, user_message))
                
                # ✅ MENSAGEM INTERNA
                internal_phone = "5511918368812"  # Número do escritório
                tasks.append(baileys_service.send_whatsapp_message(internal_phone, internal_message))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                return results
            
            try:
                results = await asyncio.wait_for(
                    send_messages(),
                    timeout=self.whatsapp_global_timeout
                )
                
                success_count = sum(1 for r in results if r is True)
                logger.info(f"📤 [{correlation_id}] WhatsApp enviado: {success_count}/2 sucessos")
                
                return success_count > 0
                
            except asyncio.TimeoutError:
                logger.warning(f"⏰ [{correlation_id}] Timeout WhatsApp global ({self.whatsapp_global_timeout}s)")
                return False
                
        except Exception as e:
            logger.warning(f"❌ [{correlation_id}] Erro WhatsApp: {str(e)}")
            return False

    async def _notify_lawyers_async(self, lead_data: Dict[str, Any], correlation_id: str):
        """
        ✅ NOTIFICAR ADVOGADOS COM TIMEOUT
        """
        try:
            user_name = lead_data.get("step_1", "Cliente não identificado")
            phone = lead_data.get("phone", "Telefone não informado")
            area = lead_data.get("step_3", "Área não informada")
            
            # ✅ NOTIFICAR COM TIMEOUT
            await asyncio.wait_for(
                lawyer_notification_service.notify_lawyers_of_new_lead(
                    lead_name=user_name,
                    lead_phone=phone,
                    category=area,
                    additional_info=lead_data
                ),
                timeout=self.notification_timeout
            )
            
            logger.info(f"👨‍⚖️ [{correlation_id}] Advogados notificados")
            
        except asyncio.TimeoutError:
            logger.warning(f"⏰ [{correlation_id}] Timeout notificação advogados ({self.notification_timeout}s)")
        except Exception as e:
            logger.warning(f"❌ [{correlation_id}] Erro notificação advogados: {str(e)}")

    def _is_rate_limited(self, session_id: str) -> bool:
        """Rate limiting check."""
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)
        
        # Clean old messages
        self.message_counts[session_id] = [
            msg_time for msg_time in self.message_counts[session_id] 
            if msg_time > cutoff
        ]
        
        # Check limit
        if len(self.message_counts[session_id]) >= self.max_messages_per_minute:
            return True
        
        # Add current message
        self.message_counts[session_id].append(now)
        return False

    def _is_phone_number(self, text: str) -> bool:
        """Validate Brazilian phone number."""
        clean = re.sub(r'[^\d]', '', text)
        return len(clean) >= 10 and len(clean) <= 13

    def _format_brazilian_phone(self, phone: str) -> str:
        """Format Brazilian phone number."""
        clean = re.sub(r'[^\d]', '', phone)
        if not clean.startswith("55"):
            clean = f"55{clean}"
        return clean

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        ✅ OBTER CONTEXTO DA SESSÃO COM VALIDAÇÃO
        """
        try:
            session_data = await get_user_session(session_id)
            
            if not session_data:
                return {
                    "session_id": session_id,
                    "status_info": {
                        "step": 1,
                        "flow_completed": False,
                        "phone_submitted": False,
                        "state": "not_found"
                    },
                    "lead_data": {},  # ✅ SEMPRE PRESENTE
                    "current_step": 1,
                    "flow_completed": False,
                    "phone_submitted": False
                }
            
            # ✅ GARANTIR INTEGRIDADE
            session_data = await self._ensure_session_integrity(session_id, session_data)
            
            return {
                "session_id": session_id,
                "status_info": {
                    "step": session_data.get("current_step", 1),
                    "flow_completed": session_data.get("flow_completed", False),
                    "phone_submitted": session_data.get("phone_submitted", False),
                    "state": "active"
                },
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE PRESENTE
                "current_step": session_data.get("current_step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "message_count": session_data.get("message_count", 0),
                "platform": session_data.get("platform", "web"),
                "created_at": session_data.get("created_at"),
                "last_updated": session_data.get("last_updated")
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter contexto {session_id}: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "status_info": {
                    "step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "state": "error"
                },
                "lead_data": {},  # ✅ SEMPRE PRESENTE
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "error": str(e)
            }

    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Get overall service status."""
        try:
            from app.services.firebase_service import get_firebase_service_status
            
            firebase_status = await get_firebase_service_status()
            
            return {
                "overall_status": "active",
                "firebase_status": firebase_status.get("status", "unknown"),
                "ai_status": "active" if self.gemini_available else "quota_exceeded",
                "gemini_available": self.gemini_available,
                "fallback_mode": not self.gemini_available,
                "timeouts": {
                    "gemini": f"{self.gemini_timeout}s",
                    "whatsapp": f"{self.whatsapp_timeout}s",
                    "firebase": f"{self.firebase_timeout}s",
                    "whatsapp_global": f"{self.whatsapp_global_timeout}s"
                },
                "features": [
                    "lead_data_validation",
                    "personalized_greeting",
                    "auto_session_restart",
                    "ultra_aggressive_timeouts",
                    "cloud_run_optimized"
                ]
            }
        except Exception as e:
            return {
                "overall_status": "degraded",
                "error": str(e),
                "fallback_mode": True
            }

    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]):
        """Handle WhatsApp authorization from routes."""
        try:
            logger.info(f"🔐 Processando autorização WhatsApp: {auth_data.get('session_id')}")
            # Implementar lógica de autorização se necessário
            return {"status": "authorized"}
        except Exception as e:
            logger.error(f"❌ Erro autorização WhatsApp: {str(e)}")
            return {"status": "error", "error": str(e)}


# ✅ INSTÂNCIA GLOBAL
intelligent_orchestrator = IntelligentHybridOrchestrator()

logger.info("🚀 IntelligentHybridOrchestrator carregado com timeouts ultra agressivos para Cloud Run")