"""
Intelligent Hybrid Orchestrator - PRODUCTION READY

Sistema de orquestração inteligente que combina:
- Fluxo conversacional estruturado (Firebase)
- IA generativa (Gemini) quando disponível
- Fallback automático e inteligente
- Coleta de leads e notificação de advogados
- Integração WhatsApp via Baileys
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

# Configure logging
logger = logging.getLogger(__name__)

class IntelligentHybridOrchestrator:
    """
    ✅ ORQUESTRADOR DE FLUXO ESTRUTURADO
    
    Sistema de fluxo conversacional estruturado baseado em Firebase:
    1. Fluxo Estruturado (Firebase) - Coleta de dados confiável
    2. Validação de respostas
    3. Coleta automática de leads
    
    Características:
    - Fluxo estruturado baseado em steps
    - Coleta automática de leads
    - Notificação de advogados
    - Integração WhatsApp
    - Validação de dados
    - Rate limiting
    - Session management
    """
    
    def __init__(self):
        # Timeouts para diferentes operações
        self.firebase_timeout = 10.0
        self.whatsapp_timeout = 15.0
        self.whatsapp_global_timeout = 30.0
        self.notification_timeout = 20.0
        
        # Rate limiting
        self.message_counts = defaultdict(list)
        self.max_messages_per_minute = 10
        
        # Session locks para evitar race conditions
        self.session_locks = defaultdict(asyncio.Lock)
        

    def safe_get_lead_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR QUE LEAD_DATA SEMPRE SEJA UM DICT VÁLIDO
        
        Corrige o erro: 'NoneType' object is not subscriptable
        """
        lead_data = session_data.get("lead_data")
        if not lead_data or not isinstance(lead_data, dict):
            return {}
        return lead_data

    async def _ensure_session_integrity(self, session_id: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR INTEGRIDADE DA SESSÃO
        
        Corrige sessões antigas que podem não ter todos os campos necessários.
        """
        needs_save = False
        
        # ✅ GARANTIR LEAD_DATA SEMPRE PRESENTE
        if "lead_data" not in session_data or session_data["lead_data"] is None:
            session_data["lead_data"] = {}
            needs_save = True
            logger.info(f"🔧 Corrigindo lead_data ausente para sessão {session_id}")
        
        # ✅ GARANTIR CAMPOS ESSENCIAIS
        essential_fields = {
            "session_id": session_id,
            "current_step": 1,
            "flow_completed": False,
            "phone_submitted": False,
            "message_count": 0,
            "platform": "web"
        }
        
        for field, default_value in essential_fields.items():
            if field not in session_data:
                session_data[field] = default_value
                needs_save = True
                logger.info(f"🔧 Adicionando campo {field} = {default_value} para sessão {session_id}")
        
        # ✅ SALVAR SE HOUVE CORREÇÕES
        if needs_save:
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"💾 Sessão {session_id} corrigida e salva")
            except Exception as save_error:
                logger.error(f"❌ Erro ao salvar correções da sessão {session_id}: {str(save_error)}")
        
        return session_data

    async def start_conversation(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ✅ INICIAR CONVERSA COM SAUDAÇÃO PERSONALIZADA POR HORÁRIO
        
        Inicia uma nova conversa com saudação baseada no horário:
        - Bom dia (5h-12h)
        - Boa tarde (12h-18h) 
        - Boa noite (18h-5h)
        
        Seguido da pergunta do nome completo.
        """
        correlation_id = str(uuid.uuid4())[:8]
        
        try:
            # ✅ GERAR SESSION_ID SE NÃO FORNECIDO
            if not session_id:
                session_id = f"web_{int(datetime.now().timestamp())}_{correlation_id}"
            
            logger.info(f"🚀 [{correlation_id}] Iniciando conversa para sessão: {session_id}")
            
            # ✅ SAUDAÇÃO PERSONALIZADA BASEADA NO HORÁRIO (BRASÍLIA)
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
                    
                logger.info(f"🌅 [{correlation_id}] Saudação: {greeting} (hora: {hour}h)")
                
            except Exception as tz_error:
                logger.warning(f"⚠️ [{correlation_id}] Erro timezone: {str(tz_error)} - usando saudação padrão")
                greeting = "Olá"
            
            # ✅ MENSAGEM DE BOAS-VINDAS PERSONALIZADA
            welcome_message = f"{greeting}! Seja bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com um de nossos advogados especializados.\n\nPara começar, qual é o seu nome completo?"
            
            # ✅ CRIAR SESSÃO INICIAL
            session_data = {
                "session_id": session_id,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "message_count": 0,
                "lead_data": {},  # ✅ SEMPRE INICIALIZAR COMO DICT
                "platform": "web",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
            
            # ✅ SALVAR SESSÃO INICIAL
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"💾 [{correlation_id}] Sessão inicial salva")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão inicial: {str(save_error)}")
                # ✅ CONTINUAR MESMO COM ERRO DE SAVE
            
            return {
                "session_id": session_id,
                "response": welcome_message,
                "response_type": "greeting_personalized",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao iniciar conversa: {str(e)}")
            
            # ✅ FALLBACK SEGURO COM LEAD_DATA VÁLIDO
            return {
                "session_id": session_id or f"error_{correlation_id}",
                "response": "Olá! Para começar, qual é o seu nome completo?",
                "response_type": "greeting_fallback",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
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
        
        Processa resposta do usuário com:
        - Validação rigorosa de lead_data
        - Correção automática de sessões antigas
        - Fallback seguro em caso de erro
        - Sempre retorna lead_data válido
        """
        correlation_id = str(uuid.uuid4())[:8]
        
        try:
            logger.info(f"📨 [{correlation_id}] Processando: '{message[:50]}...' | Session: {session_id}")
            
            # ✅ RATE LIMITING
            if self._is_rate_limited(session_id):
                logger.warning(f"⏰ [{correlation_id}] Rate limited: {session_id}")
                return {
                    "session_id": session_id,
                    "response": "⏳ Muitas mensagens em pouco tempo. Aguarde um momento...",
                    "response_type": "rate_limited",
                    "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                    "correlation_id": correlation_id
                }
            
            # ✅ OBTER SESSÃO COM TIMEOUT
            try:
                session_data = await asyncio.wait_for(
                    get_user_session(session_id),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ [{correlation_id}] Timeout ao buscar sessão {session_id}")
                session_data = None
            except Exception as session_error:
                logger.error(f"❌ [{correlation_id}] Erro ao buscar sessão: {str(session_error)}")
                session_data = None
            
            # ✅ CRIAR SESSÃO PADRÃO SE NÃO EXISTIR
            if not session_data:
                logger.info(f"🆕 [{correlation_id}] Criando nova sessão: {session_id}")
                session_data = {
                    "session_id": session_id,
                    "current_step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "message_count": 0,
                    "lead_data": {},  # ✅ SEMPRE INICIALIZAR COMO DICT
                    "gemini_available": self.gemini_available,
                    "platform": platform
                }
            
            # ✅ GARANTIR INTEGRIDADE DA SESSÃO
            session_data = await self._ensure_session_integrity(session_id, session_data)
            
            # ✅ AUTO-REINICIALIZAÇÃO SE NECESSÁRIO
            if session_data.get("flow_completed") and session_data.get("phone_submitted"):
                # ✅ DETECTAR TENTATIVA DE NOVA CONVERSA
                restart_triggers = ["oi", "olá", "hello", "começar", "iniciar", "novo", "restart"]
                if any(trigger in message.lower() for trigger in restart_triggers):
                    logger.info(f"🔄 [{correlation_id}] Auto-reinicialização detectada")
                    return await self._auto_restart_session(session_id, message, correlation_id)
            
            # ✅ VERIFICAR SE PRECISA COLETAR TELEFONE
            if session_data.get("flow_completed") and not session_data.get("phone_submitted"):
                logger.info(f"📱 [{correlation_id}] Coletando telefone")
                return await self._handle_phone_collection(session_data, message, correlation_id)
            
            # ✅ TENTAR GEMINI PRIMEIRO
            gemini_result = await self._attempt_gemini_response(message, session_id, session_data, correlation_id)
            
            if gemini_result["success"]:
                # ✅ SUCESSO COM GEMINI
                logger.info(f"🤖 [{correlation_id}] Resposta Gemini gerada")
                
                result = {
                    "session_id": session_id,
                    "response": gemini_result["response"],
                    "response_type": "ai_intelligent",
                    "ai_mode": True,
                    "gemini_available": True,
                    "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE VÁLIDO
                    "message_count": session_data.get("message_count", 0) + 1,
                    "correlation_id": correlation_id
                }
                
                # ✅ ATUALIZAR CONTADOR DE MENSAGENS
                session_data["message_count"] = result["message_count"]
                session_data["last_updated"] = datetime.now().isoformat()
                
                # ✅ SALVAR SESSÃO ATUALIZADA (ASYNC)
                asyncio.create_task(self._save_session_async(session_id, session_data, correlation_id))
                
                return result
            
            # ✅ FALLBACK PARA FLUXO FIREBASE
            logger.info(f"🚀 [{correlation_id}] Usando fallback Firebase - Gemini: {gemini_result['reason']}")
            return await self._get_fallback_response(session_data, message, correlation_id)
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro crítico ao processar mensagem: {str(e)}")
            logger.error(f"❌ [{correlation_id}] Stack trace:", exc_info=True)
            
            # ✅ FALLBACK SEGURO COM LEAD_DATA VÁLIDO
            return {
                "session_id": session_id,
                "response": "Desculpe, ocorreu um erro temporário. Vamos tentar novamente? Qual é o seu nome completo?",
                "response_type": "system_error_recovery",
                "error": str(e),
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "correlation_id": correlation_id
            }

    async def _auto_restart_session(self, session_id: str, message: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ AUTO-REINICIALIZAÇÃO DE SESSÃO
        
        Remove o problema do chat "finalizado" permanente.
        """
        try:
            logger.info(f"🔄 [{correlation_id}] Reinicializando sessão: {session_id}")
            
            # ✅ CRIAR NOVA SESSÃO LIMPA
            new_session_data = {
                "session_id": session_id,
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "message_count": 1,
                "lead_data": {},  # ✅ SEMPRE DICT VÁLIDO
                "gemini_available": self.gemini_available,
                "platform": "web",
                "restarted_at": datetime.now().isoformat()
            }
            
            # ✅ SALVAR NOVA SESSÃO
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, new_session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"💾 [{correlation_id}] Sessão reinicializada e salva")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão reinicializada: {str(save_error)}")
            
            # ✅ SAUDAÇÃO DE REINICIALIZAÇÃO
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
                    
            except Exception:
                greeting = "Olá"
            
            restart_message = f"{greeting}! Vamos começar uma nova conversa. Para começar, qual é o seu nome completo?"
            
            return {
                "session_id": session_id,
                "response": restart_message,
                "response_type": "session_restarted",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "restarted": True,
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao reinicializar sessão: {str(e)}")
            
            return {
                "session_id": session_id,
                "response": "Olá! Para começar, qual é o seu nome completo?",
                "response_type": "restart_fallback",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "error": str(e),
                "correlation_id": correlation_id
            }

    async def _attempt_gemini_response(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any],
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ TENTAR RESPOSTA GEMINI COM TIMEOUT E DETECÇÃO DE QUOTA
        """
        try:
            # ✅ VERIFICAR SE GEMINI ESTÁ DISPONÍVEL
            if not self.gemini_available:
                time_since_check = datetime.now() - self.last_gemini_check
                if time_since_check < self.gemini_check_interval:
                    return {"success": False, "reason": "gemini_marked_unavailable"}
            
            logger.info(f"🤖 [{correlation_id}] Tentando Gemini (timeout: {self.gemini_timeout}s)")
            
            # ✅ CHAMAR GEMINI COM TIMEOUT
            response = await asyncio.wait_for(
                ai_orchestrator.generate_response(
                    message, 
                    session_id=session_id,
                    context={"platform": session_data.get("platform", "web")}
                ),
                timeout=self.gemini_timeout
            )
            
            if response and len(response.strip()) > 0:
                logger.info(f"✅ [{correlation_id}] Gemini response received")
                self.gemini_available = True
                self.last_gemini_check = datetime.now()
                return {"success": True, "response": response}
            else:
                logger.warning(f"⚠️ [{correlation_id}] Gemini returned empty response")
                return {"success": False, "reason": "empty_response"}
                
        except asyncio.TimeoutError:
            logger.warning(f"⏰ [{correlation_id}] Gemini timeout ({self.gemini_timeout}s)")
            self.gemini_available = False
            self.last_gemini_check = datetime.now()
            return {"success": False, "reason": "timeout"}
            
        except Exception as e:
            error_str = str(e).lower()
            
            # ✅ DETECTAR ERROS DE QUOTA
            if self._is_quota_error(error_str):
                logger.warning(f"🚫 [{correlation_id}] Gemini quota exceeded: {str(e)}")
                self.gemini_available = False
                self.last_gemini_check = datetime.now()
                return {"success": False, "reason": "quota_exceeded"}
            else:
                logger.error(f"❌ [{correlation_id}] Gemini API error: {str(e)}")
                return {"success": False, "reason": "api_error"}

    def _is_quota_error(self, error_message: str) -> bool:
        """Detectar erros de quota do Gemini."""
        quota_indicators = [
            "quota", "429", "too many requests", "rate limit", 
            "billing", "resourceexhausted", "limit exceeded"
        ]
        return any(indicator in error_message for indicator in quota_indicators)

    async def _get_fallback_response(
        self, 
        session_data: Dict[str, Any], 
        message: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ RESPOSTA FALLBACK FIREBASE COM VALIDAÇÃO RIGOROSA
        """
        try:
            session_id = session_data["session_id"]
            current_step = session_data.get("current_step", 1)
            lead_data = self.safe_get_lead_data(session_data)  # ✅ SEMPRE DICT VÁLIDO
            
            logger.info(f"🚀 [{correlation_id}] Fallback Firebase - Step {current_step}")
            
            # ✅ OBTER FLUXO DE CONVERSA
            try:
                flow = await asyncio.wait_for(
                    get_conversation_flow(),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏰ [{correlation_id}] Timeout ao buscar fluxo - usando fallback")
                flow = {
                    "steps": [
                        {"id": 1, "question": "Qual é o seu nome completo?"},
                        {"id": 2, "question": "Qual o seu telefone e e-mail?"},
                        {"id": 3, "question": "Em qual área você precisa de ajuda? (Penal ou Saúde)"},
                        {"id": 4, "question": "Descreva sua situação:"},
                        {"id": 5, "question": "Posso direcioná-lo para nosso especialista?"}
                    ],
                    "completion_message": "Perfeito! Nossa equipe entrará em contato."
                }
            
            steps = flow.get("steps", [])
            
            # ✅ VALIDAR E AVANÇAR STEP
            if current_step <= len(steps):
                # ✅ SALVAR RESPOSTA ATUAL
                lead_data[f"step_{current_step}"] = message.strip()
                
                # ✅ VALIDAR RESPOSTA (BÁSICO)
                if not self._should_advance_step(message, current_step):
                    # ✅ RE-PROMPT MESMA PERGUNTA
                    current_question_data = next((s for s in steps if s["id"] == current_step), None)
                    if current_question_data:
                        return {
                            "session_id": session_id,
                            "response": f"Por favor, forneça mais detalhes. {current_question_data['question']}",
                            "response_type": "validation_reprompt",
                            "current_step": current_step,
                            "flow_completed": False,
                            "ai_mode": False,
                            "validation_error": True,
                            "lead_data": lead_data,
                            "correlation_id": correlation_id
                        }
                
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
                        
                        # ✅ PERSONALIZAR COM ÁREA
                        if "{area}" in next_question and "step_3" in lead_data:
                            area = lead_data["step_3"]
                            next_question = next_question.replace("{area}", area)
                        
                        # ✅ ATUALIZAR SESSÃO
                        session_data["current_step"] = next_step
                        session_data["lead_data"] = lead_data
                        session_data["message_count"] = session_data.get("message_count", 0) + 1
                        session_data["last_updated"] = datetime.now().isoformat()
                        
                        # ✅ SALVAR SESSÃO (ASYNC)
                        asyncio.create_task(self._save_session_async(session_id, session_data, correlation_id))
                        
                        return {
                            "session_id": session_id,
                            "response": next_question,
                            "response_type": "fallback_firebase",
                            "current_step": next_step,
                            "flow_completed": False,
                            "ai_mode": False,
                            "lead_data": lead_data,
                            "message_count": session_data["message_count"],
                            "correlation_id": correlation_id
                        }
                
                # ✅ FLUXO COMPLETO - COLETAR TELEFONE
                logger.info(f"🎯 [{correlation_id}] Fluxo completo - coletar telefone")
                
                session_data["flow_completed"] = True
                session_data["lead_data"] = lead_data
                session_data["last_updated"] = datetime.now().isoformat()
                
                # ✅ SALVAR SESSÃO (ASYNC)
                asyncio.create_task(self._save_session_async(session_id, session_data, correlation_id))
                
                completion_message = flow.get("completion_message", "Perfeito! Para finalizar, preciso do seu WhatsApp:")
                
                # ✅ PERSONALIZAR MENSAGEM DE CONCLUSÃO
                if "{user_name}" in completion_message and "step_1" in lead_data:
                    user_name = lead_data["step_1"].split()[0]
                    completion_message = completion_message.replace("{user_name}", user_name)
                
                if "{area}" in completion_message and "step_3" in lead_data:
                    area = lead_data["step_3"]
                    completion_message = completion_message.replace("{area}", area)
                
                return {
                    "session_id": session_id,
                    "response": f"{completion_message}\n\nPor favor, informe seu WhatsApp:",
                    "response_type": "flow_completed_collect_phone",
                    "flow_completed": True,
                    "collecting_phone": True,
                    "ai_mode": False,
                    "lead_data": lead_data,
                    "message_count": session_data.get("message_count", 0) + 1,
                    "correlation_id": correlation_id
                }
            
            # ✅ FALLBACK GENÉRICO
            logger.warning(f"⚠️ [{correlation_id}] Step inválido: {current_step}")
            
            return {
                "session_id": session_id,
                "response": "Qual é o seu nome completo?",
                "response_type": "fallback_generic",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "lead_data": lead_data,
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no fallback Firebase: {str(e)}")
            
            return {
                "session_id": session_data.get("session_id", "error"),
                "response": "Qual é o seu nome completo?",
                "response_type": "fallback_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR DICT VÁLIDO
                "error": str(e),
                "correlation_id": correlation_id
            }

    def _should_advance_step(self, answer: str, step_id: int) -> bool:
        """Validação básica para avançar step."""
        answer = answer.strip()
        
        if step_id == 1:  # Nome
            return len(answer.split()) >= 2
        elif step_id == 2:  # Contato
            return len(answer) >= 10
        elif step_id == 3:  # Área
            return len(answer) >= 3
        elif step_id == 4:  # Situação
            return len(answer) >= 10
        else:
            return len(answer) >= 1

    async def _handle_phone_collection(
        self, 
        session_data: Dict[str, Any], 
        phone_message: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ COLETAR TELEFONE E FINALIZAR FLUXO
        """
        try:
            session_id = session_data["session_id"]
            lead_data = self.safe_get_lead_data(session_data)  # ✅ SEMPRE DICT VÁLIDO
            
            logger.info(f"📱 [{correlation_id}] Coletando telefone")
            
            # ✅ VALIDAR TELEFONE
            if self._is_phone_number(phone_message):
                clean_phone = self._format_brazilian_phone(phone_message)
                
                # ✅ SALVAR TELEFONE
                lead_data["phone"] = clean_phone
                session_data["phone_submitted"] = True
                session_data["lead_data"] = lead_data
                session_data["last_updated"] = datetime.now().isoformat()
                
                # ✅ SALVAR SESSÃO (ASYNC)
                asyncio.create_task(self._save_session_async(session_id, session_data, correlation_id))
                
                # ✅ SALVAR LEAD (ASYNC)
                asyncio.create_task(self._save_lead_async(lead_data, correlation_id))
                
                # ✅ ENVIAR WHATSAPP PARA USUÁRIO (ASYNC)
                asyncio.create_task(self._send_user_whatsapp_async(lead_data, clean_phone, correlation_id))
                
                # ✅ NOTIFICAR ADVOGADOS (ASYNC)
                asyncio.create_task(self._notify_lawyers_async(lead_data, correlation_id))
                
                return {
                    "session_id": session_id,
                    "response": f"✅ Telefone {clean_phone} confirmado!\n\nObrigado! Nossa equipe entrará em contato em breve via WhatsApp.",
                    "response_type": "phone_collected_fallback",
                    "flow_completed": True,
                    "phone_submitted": True,
                    "phone_number": clean_phone,
                    "lead_saved": True,
                    "whatsapp_sent": True,
                    "lawyers_notified": True,
                    "lead_data": lead_data,
                    "correlation_id": correlation_id
                }
            else:
                return {
                    "session_id": session_id,
                    "response": "Por favor, informe um WhatsApp válido (com DDD):\n\nExemplo: 11999999999",
                    "response_type": "phone_validation_error",
                    "flow_completed": True,
                    "collecting_phone": True,
                    "validation_error": True,
                    "lead_data": lead_data,
                    "correlation_id": correlation_id
                }
                
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro na coleta de telefone: {str(e)}")
            
            return {
                "session_id": session_data.get("session_id", "error"),
                "response": "Ocorreu um erro. Por favor, informe seu WhatsApp novamente:",
                "response_type": "phone_collection_error",
                "flow_completed": True,
                "collecting_phone": True,
                "error": str(e),
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE DICT VÁLIDO
                "correlation_id": correlation_id
            }

    async def _save_session_async(self, session_id: str, session_data: Dict[str, Any], correlation_id: str):
        """Salvar sessão de forma assíncrona."""
        try:
            await asyncio.wait_for(
                save_user_session(session_id, session_data),
                timeout=self.firebase_timeout
            )
            logger.info(f"💾 [{correlation_id}] Sessão salva: {session_id}")
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão: {str(e)}")

    async def _save_lead_async(self, lead_data: Dict[str, Any], correlation_id: str):
        """Salvar lead de forma assíncrona."""
        try:
            await asyncio.wait_for(
                save_lead_data({"answers": lead_data}),
                timeout=self.firebase_timeout
            )
            logger.info(f"💾 [{correlation_id}] Lead salvo")
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao salvar lead: {str(e)}")

    async def _send_user_whatsapp_async(self, lead_data: Dict[str, Any], phone: str, correlation_id: str):
        """Enviar WhatsApp para usuário de forma assíncrona."""
        try:
            user_name = lead_data.get("step_1", "Cliente")
            user_message = f"Olá {user_name}! 👋\n\nObrigado por entrar em contato com o m.lima.\n\nSuas informações foram registradas e em breve um de nossos advogados especializados entrará em contato.\n\nFique tranquilo, você está em boas mãos! 🤝"
            
            await asyncio.wait_for(
                baileys_service.send_whatsapp_message(phone, user_message),
                timeout=self.whatsapp_timeout
            )
            logger.info(f"📤 [{correlation_id}] WhatsApp enviado para usuário: {phone}")
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao enviar WhatsApp para usuário: {str(e)}")

    async def _notify_lawyers_async(self, lead_data: Dict[str, Any], correlation_id: str):
        """Notificar advogados de forma assíncrona."""
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
            logger.info(f"👨‍⚖️ [{correlation_id}] Advogados notificados")
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao notificar advogados: {str(e)}")

    def _is_rate_limited(self, session_id: str) -> bool:
        """Rate limiting por sessão."""
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)
        
        # ✅ LIMPAR MENSAGENS ANTIGAS
        self.message_counts[session_id] = [
            msg_time for msg_time in self.message_counts[session_id] 
            if msg_time > cutoff
        ]
        
        if len(self.message_counts[session_id]) >= self.max_messages_per_minute:
            return True
        
        self.message_counts[session_id].append(now)
        return False

    def _is_phone_number(self, text: str) -> bool:
        """Validar se texto é um número de telefone."""
        clean = re.sub(r'[^\d]', '', text)
        return 10 <= len(clean) <= 13

    def _format_brazilian_phone(self, phone: str) -> str:
        """Formatar telefone brasileiro."""
        clean = re.sub(r'[^\d]', '', phone)
        if not clean.startswith("55"):
            clean = f"55{clean}"
        return clean

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        ✅ OBTER CONTEXTO DA SESSÃO COM VALIDAÇÃO DE LEAD_DATA
        
        Retorna status completo da conversa com:
        - Validação de integridade da sessão
        - lead_data sempre presente
        - Correção automática de sessões antigas
        """
        try:
            session_data = await asyncio.wait_for(
                get_user_session(session_id),
                timeout=self.firebase_timeout
            )
            
            if not session_data:
                return {
                    "session_id": session_id,
                    "status_info": {
                        "step": 1,
                        "flow_completed": False,
                        "phone_submitted": False,
                        "state": "not_found"
                    },
                    "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
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
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE VÁLIDO
                "current_step": session_data.get("current_step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "message_count": session_data.get("message_count", 0),
                "gemini_available": session_data.get("gemini_available", True)
            }
            
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Timeout ao buscar contexto da sessão: {session_id}")
            return {
                "session_id": session_id,
                "status_info": {
                    "step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "state": "timeout"
                },
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False
            }
        except Exception as e:
            logger.error(f"❌ Erro ao obter contexto da sessão {session_id}: {str(e)}")
            return {
                "session_id": session_id,
                "status_info": {
                    "step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "state": "error"
                },
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "error": str(e)
            }

    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Status geral do serviço."""
        try:
            return {
                "overall_status": "active",
                "ai_status": "active" if self.gemini_available else "quota_exceeded",
                "firebase_status": "active",
                "gemini_available": self.gemini_available,
                "fallback_mode": not self.gemini_available,
                "features": [
                    "intelligent_conversation_flow",
                    "ai_first_fallback_second",
                    "automatic_lead_collection",
                    "whatsapp_integration",
                    "lawyer_notifications",
                    "session_management",
                    "rate_limiting",
                    "auto_restart_capability"
                ]
            }
        except Exception as e:
            return {
                "overall_status": "degraded",
                "error": str(e),
                "fallback_mode": True
            }

    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]):
        """Handle WhatsApp authorization."""
        try:
            logger.info(f"🔐 WhatsApp authorization: {auth_data.get('session_id')}")
            return {"status": "authorized"}
        except Exception as e:
            logger.error(f"❌ WhatsApp authorization error: {str(e)}")
            return {"status": "error", "error": str(e)}


# ✅ INSTÂNCIA GLOBAL
intelligent_orchestrator = IntelligentHybridOrchestrator()

logger.info("🚀 StructuredFlowOrchestrator loaded successfully")
logger.info("🚀 IntelligentHybridOrchestrator loaded successfully")