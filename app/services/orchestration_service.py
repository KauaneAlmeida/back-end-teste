"""
Intelligent Hybrid Orchestration Service - PRODUCTION READY

Sistema de orquestração inteligente que combina:
- IA Gemini para respostas naturais
- Fallback Firebase para fluxo estruturado
- Integração WhatsApp via Baileys
- Validação rigorosa de dados
- Auto-recovery em caso de erros
- Rate limiting e proteção contra spam
- Logs estruturados com correlation IDs
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

# Firebase imports
from app.services.firebase_service import (
    get_conversation_flow, 
    save_user_session, 
    get_user_session,
    save_lead_data
)

# AI imports
from app.services.ai_chain import ai_orchestrator

# WhatsApp imports
from app.services.baileys_service import baileys_service

# Lawyer notification imports
from app.services.lawyer_notification_service import lawyer_notification_service

# Configure logging
logger = logging.getLogger(__name__)

# Rate limiting storage
user_message_counts = defaultdict(list)
RATE_LIMIT_MESSAGES = 10
RATE_LIMIT_WINDOW = 60  # seconds


class IntelligentHybridOrchestrator:
    """
    ✅ ORQUESTRADOR INTELIGENTE HÍBRIDO - PRODUCTION READY
    
    Combina IA Gemini + Fallback Firebase com:
    - Validação rigorosa de lead_data
    - Saudação personalizada por horário
    - Auto-recovery de erros
    - Rate limiting
    - Logs estruturados
    - Timeouts otimizados para Cloud Run
    """
    
    def __init__(self):
        self.gemini_available = True
        self.last_gemini_check = datetime.now()
        self.gemini_check_interval = timedelta(minutes=5)
        
        # ✅ TIMEOUTS OTIMIZADOS PARA CLOUD RUN
        self.gemini_timeout = 8  # Reduzido de 15s
        self.whatsapp_timeout = 10  # Reduzido de 15s
        self.firebase_timeout = 5  # Reduzido de 10s
        
        logger.info("🤖 Intelligent Hybrid Orchestrator initialized - PRODUCTION READY")

    def safe_get_lead_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR QUE LEAD_DATA SEMPRE SEJA UM DICT VÁLIDO
        
        Esta função resolve o erro HTTP 500 causado por lead_data undefined/null
        """
        lead_data = session_data.get("lead_data")
        if not lead_data or not isinstance(lead_data, dict):
            logger.warning("⚠️ lead_data inválido ou ausente - retornando dict vazio")
            return {}
        return lead_data

    async def _ensure_session_integrity(self, session_id: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ✅ GARANTIR INTEGRIDADE DA SESSÃO
        
        Corrige sessões antigas que não têm lead_data ou têm dados corrompidos
        """
        needs_save = False
        
        # ✅ CORRIGIR SESSÕES ANTIGAS SEM LEAD_DATA
        if "lead_data" not in session_data or session_data["lead_data"] is None:
            session_data["lead_data"] = {}
            needs_save = True
            logger.info(f"🔧 Corrigindo sessão {session_id} - adicionando lead_data")
        
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
                needs_save = True
        
        # ✅ SALVAR SE HOUVER CORREÇÕES
        if needs_save:
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"✅ Sessão {session_id} corrigida e salva")
            except asyncio.TimeoutError:
                logger.error(f"⏰ Timeout ao salvar correções da sessão {session_id}")
            except Exception as e:
                logger.error(f"❌ Erro ao salvar correções da sessão {session_id}: {str(e)}")
        
        return session_data

    def _get_personalized_greeting(self) -> str:
        """
        ✅ SAUDAÇÃO PERSONALIZADA POR HORÁRIO - BRASÍLIA
        
        Retorna saudação baseada no horário de Brasília:
        - Bom dia (5h-12h)
        - Boa tarde (12h-18h) 
        - Boa noite (18h-5h)
        """
        try:
            # ✅ HORÁRIO DE BRASÍLIA
            brasilia_tz = pytz.timezone('America/Sao_Paulo')
            now = datetime.now(brasilia_tz)
            hour = now.hour
            
            # ✅ SAUDAÇÃO POR HORÁRIO
            if 5 <= hour < 12:
                greeting = "Bom dia"
            elif 12 <= hour < 18:
                greeting = "Boa tarde"
            else:
                greeting = "Boa noite"
            
            logger.info(f"🌅 Saudação personalizada: {greeting} (hora: {hour}h)")
            
            # ✅ MENSAGEM COMPLETA
            return f"{greeting}! Bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com nossos advogados especializados.\n\nPara começar, qual é o seu nome completo?"
            
        except Exception as e:
            logger.error(f"❌ Erro ao gerar saudação personalizada: {str(e)}")
            # ✅ FALLBACK SEGURO
            return "Olá! Bem-vindo ao m.lima. Para começar, qual é o seu nome completo?"

    async def start_conversation(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ✅ INICIAR CONVERSA COM SAUDAÇÃO PERSONALIZADA
        
        Retorna saudação baseada no horário + pergunta do nome
        Não exige que usuário digite "oi" primeiro
        """
        try:
            # ✅ GERAR SESSION_ID SE NECESSÁRIO
            if not session_id:
                session_id = f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            
            correlation_id = f"start_{uuid.uuid4().hex[:8]}"
            logger.info(f"🚀 [{correlation_id}] Iniciando conversa: {session_id}")
            
            # ✅ SAUDAÇÃO PERSONALIZADA POR HORÁRIO
            greeting_message = self._get_personalized_greeting()
            
            # ✅ CRIAR SESSÃO INICIAL LIMPA
            session_data = {
                "session_id": session_id,
                "platform": "web",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "state": "active",
                "message_count": 0,
                "lead_data": {},  # ✅ SEMPRE INICIALIZAR COMO DICT VAZIO
                "correlation_id": correlation_id
            }
            
            # ✅ SALVAR SESSÃO
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"✅ [{correlation_id}] Sessão inicial salva: {session_id}")
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao salvar sessão inicial")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão: {str(save_error)}")
            
            # ✅ RESPOSTA PADRONIZADA
            return {
                "session_id": session_id,
                "response": greeting_message,
                "response_type": "personalized_greeting",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "correlation_id": correlation_id,
                "greeting_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao iniciar conversa: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            fallback_session_id = session_id or f"error_{uuid.uuid4().hex[:8]}"
            return {
                "session_id": fallback_session_id,
                "response": "Olá! Bem-vindo ao m.lima. Para começar, qual é o seu nome completo?",
                "response_type": "fallback_greeting",
                "current_step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "phone_submitted": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "error": str(e)
            }

    def _is_rate_limited(self, session_id: str) -> bool:
        """Check if user is rate limited."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW)
        
        # Clean old messages
        user_message_counts[session_id] = [
            msg_time for msg_time in user_message_counts[session_id] 
            if msg_time > cutoff
        ]
        
        # Check limit
        if len(user_message_counts[session_id]) >= RATE_LIMIT_MESSAGES:
            return True
        
        # Add current message
        user_message_counts[session_id].append(now)
        return False

    async def process_message(
        self, 
        message: str, 
        session_id: str, 
        phone_number: str = None,
        platform: str = "web"
    ) -> Dict[str, Any]:
        """
        ✅ PROCESSAR MENSAGEM COM VALIDAÇÃO RIGOROSA
        
        Função principal que:
        1. Valida lead_data rigorosamente
        2. Aplica rate limiting
        3. Tenta IA Gemini primeiro
        4. Fallback para Firebase se necessário
        5. Sempre retorna lead_data válido
        """
        correlation_id = f"msg_{uuid.uuid4().hex[:8]}"
        
        try:
            logger.info(f"📨 [{correlation_id}] Processando mensagem: {message[:50]}... (session: {session_id})")
            
            # ✅ RATE LIMITING
            if self._is_rate_limited(session_id):
                logger.warning(f"⏰ [{correlation_id}] Rate limit atingido para {session_id}")
                return {
                    "session_id": session_id,
                    "response": "⏳ Muitas mensagens em pouco tempo. Aguarde um momento antes de enviar outra mensagem.",
                    "response_type": "rate_limited",
                    "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                    "correlation_id": correlation_id
                }
            
            # ✅ OBTER OU CRIAR SESSÃO
            session_data = await self._get_or_create_session(session_id, platform, correlation_id)
            
            # ✅ GARANTIR INTEGRIDADE DA SESSÃO
            session_data = await self._ensure_session_integrity(session_id, session_data)
            
            # ✅ VERIFICAR SE PRECISA AUTO-REINICIAR
            if session_data.get("state") == "completed" and session_data.get("flow_completed"):
                logger.info(f"🔄 [{correlation_id}] Auto-reiniciando sessão finalizada: {session_id}")
                return await self._auto_restart_session(session_id, message, correlation_id)
            
            # ✅ INCREMENTAR CONTADOR DE MENSAGENS
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            session_data["last_updated"] = datetime.now().isoformat()
            session_data["correlation_id"] = correlation_id
            
            # ✅ TENTAR IA GEMINI PRIMEIRO
            gemini_result = await self._attempt_gemini_response(message, session_id, session_data, correlation_id)
            
            if gemini_result["success"]:
                logger.info(f"✅ [{correlation_id}] Resposta Gemini gerada com sucesso")
                
                # ✅ SALVAR SESSÃO COM LEAD_DATA VÁLIDO
                session_data["gemini_available"] = True
                session_data["lead_data"] = self.safe_get_lead_data(session_data)
                
                try:
                    await asyncio.wait_for(
                        save_user_session(session_id, session_data),
                        timeout=self.firebase_timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(f"⏰ [{correlation_id}] Timeout ao salvar sessão pós-Gemini")
                except Exception as save_error:
                    logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão: {str(save_error)}")
                
                return {
                    "session_id": session_id,
                    "response": gemini_result["response"],
                    "response_type": "ai_intelligent",
                    "ai_mode": True,
                    "gemini_available": True,
                    "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE VÁLIDO
                    "correlation_id": correlation_id,
                    "message_count": session_data["message_count"]
                }
            
            # ✅ FALLBACK PARA FIREBASE
            logger.info(f"⚡ [{correlation_id}] Ativando fallback Firebase para {session_id}")
            session_data["gemini_available"] = False
            
            fallback_result = await self._get_fallback_response(session_data, message, correlation_id)
            
            # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
            fallback_result["lead_data"] = self.safe_get_lead_data(session_data)
            fallback_result["correlation_id"] = correlation_id
            
            return fallback_result
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro crítico no processamento: {str(e)}")
            logger.error(f"❌ [{correlation_id}] Stack trace:", exc_info=True)
            
            # ✅ FALLBACK SEGURO COM LEAD_DATA VÁLIDO
            return {
                "session_id": session_id,
                "response": "Desculpe, ocorreu um erro temporário. Vamos tentar novamente?",
                "response_type": "system_error_recovery",
                "error": str(e),
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "correlation_id": correlation_id,
                "recovery_mode": True
            }

    async def _get_or_create_session(self, session_id: str, platform: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ OBTER OU CRIAR SESSÃO COM LEAD_DATA VÁLIDO
        """
        try:
            # ✅ TENTAR OBTER SESSÃO EXISTENTE
            session_data = await asyncio.wait_for(
                get_user_session(session_id),
                timeout=self.firebase_timeout
            )
            
            if session_data:
                logger.info(f"📋 [{correlation_id}] Sessão existente carregada: {session_id}")
                return session_data
            
        except asyncio.TimeoutError:
            logger.error(f"⏰ [{correlation_id}] Timeout ao buscar sessão - criando nova")
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao buscar sessão: {str(e)} - criando nova")
        
        # ✅ CRIAR NOVA SESSÃO COM LEAD_DATA INICIALIZADO
        logger.info(f"🆕 [{correlation_id}] Criando nova sessão: {session_id}")
        return {
            "session_id": session_id,
            "platform": platform,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "current_step": 1,
            "flow_completed": False,
            "phone_submitted": False,
            "gemini_available": True,
            "state": "active",
            "message_count": 0,
            "lead_data": {},  # ✅ SEMPRE INICIALIZAR COMO DICT VAZIO
            "correlation_id": correlation_id
        }

    async def _attempt_gemini_response(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any],
        correlation_id: str
    ) -> Dict[str, bool]:
        """
        ✅ TENTAR RESPOSTA GEMINI COM TIMEOUT OTIMIZADO
        """
        try:
            logger.info(f"🤖 [{correlation_id}] Tentando resposta Gemini para {session_id}")
            
            # ✅ TIMEOUT REDUZIDO PARA CLOUD RUN
            response = await asyncio.wait_for(
                ai_orchestrator.generate_response(
                    message, 
                    session_id=session_id,
                    context={"platform": session_data.get("platform", "web")}
                ),
                timeout=self.gemini_timeout
            )
            
            if response and len(response.strip()) > 0:
                logger.info(f"✅ [{correlation_id}] Resposta Gemini válida recebida")
                self.gemini_available = True
                return {"success": True, "response": response}
            else:
                logger.warning(f"⚠️ [{correlation_id}] Resposta Gemini vazia")
                return {"success": False, "error": "empty_response"}
                
        except asyncio.TimeoutError:
            logger.error(f"⏰ [{correlation_id}] Timeout Gemini ({self.gemini_timeout}s)")
            self.gemini_available = False
            return {"success": False, "error": "timeout"}
            
        except Exception as e:
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["quota", "429", "resourceexhausted", "billing"]):
                logger.error(f"🚫 [{correlation_id}] Gemini quota/billing issue: {str(e)}")
                self.gemini_available = False
            else:
                logger.error(f"❌ [{correlation_id}] Erro Gemini: {str(e)}")
            
            return {"success": False, "error": str(e)}

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
            logger.info(f"⚡ [{correlation_id}] Processando fallback Firebase para {session_id}")
            
            # ✅ VERIFICAR SE ESTÁ COLETANDO TELEFONE
            if session_data.get("flow_completed") and not session_data.get("phone_submitted"):
                return await self._handle_phone_collection(session_id, session_data, message, correlation_id)
            
            # ✅ PROCESSAR FLUXO DE CONVERSA
            return await self._process_conversation_flow(session_data, message, correlation_id)
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no fallback Firebase: {str(e)}")
            
            # ✅ FALLBACK DO FALLBACK
            return {
                "session_id": session_data.get("session_id", "unknown"),
                "response": "Desculpe, vamos tentar novamente. Qual é o seu nome completo?",
                "response_type": "fallback_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "error": str(e)
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
            current_step = session_data.get("current_step", 1)
            
            # ✅ GARANTIR LEAD_DATA VÁLIDO
            lead_data = self.safe_get_lead_data(session_data)
            
            logger.info(f"📝 [{correlation_id}] Processando step {current_step} para {session_id}")
            
            # ✅ OBTER FLUXO DE CONVERSA
            try:
                flow = await asyncio.wait_for(
                    get_conversation_flow(),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao buscar fluxo - usando padrão")
                flow = self._get_default_flow()
            except Exception as flow_error:
                logger.error(f"❌ [{correlation_id}] Erro ao buscar fluxo: {str(flow_error)}")
                flow = self._get_default_flow()
            
            steps = flow.get("steps", [])
            
            # ✅ VALIDAR E NORMALIZAR RESPOSTA
            normalized_answer = self._validate_and_normalize_answer(message, current_step)
            
            if not normalized_answer:
                # ✅ RESPOSTA INVÁLIDA - REPETIR PERGUNTA
                current_question = self._get_question_for_step(steps, current_step)
                logger.warning(f"⚠️ [{correlation_id}] Resposta inválida para step {current_step}")
                
                return {
                    "session_id": session_id,
                    "response": f"Por favor, forneça uma resposta mais completa. {current_question}",
                    "response_type": "validation_error",
                    "current_step": current_step,
                    "flow_completed": False,
                    "lead_data": lead_data,  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                    "validation_error": True
                }
            
            # ✅ SALVAR RESPOSTA VÁLIDA
            lead_data[f"step_{current_step}"] = normalized_answer
            session_data["lead_data"] = lead_data
            
            logger.info(f"💾 [{correlation_id}] Resposta salva para step {current_step}: {normalized_answer[:30]}...")
            
            # ✅ AVANÇAR PARA PRÓXIMO STEP
            next_step = current_step + 1
            session_data["current_step"] = next_step
            
            # ✅ VERIFICAR SE FLUXO COMPLETOU
            if next_step > len(steps):
                logger.info(f"🎯 [{correlation_id}] Fluxo completado para {session_id}")
                return await self._complete_conversation_flow(session_data, flow, correlation_id)
            
            # ✅ PRÓXIMA PERGUNTA
            next_question = self._get_question_for_step(steps, next_step)
            next_question = self._personalize_question(next_question, lead_data)
            
            # ✅ SALVAR SESSÃO
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao salvar sessão - continuando")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão: {str(save_error)}")
            
            return {
                "session_id": session_id,
                "response": next_question,
                "response_type": "fallback_firebase",
                "current_step": next_step,
                "flow_completed": False,
                "lead_data": lead_data,  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "step_completed": current_step
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no processamento do fluxo: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_data.get("session_id", "unknown"),
                "response": "Vamos continuar. Qual é o seu nome completo?",
                "response_type": "flow_error_recovery",
                "current_step": 1,
                "flow_completed": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "error": str(e)
            }

    def _get_default_flow(self) -> Dict[str, Any]:
        """Fluxo padrão em caso de erro Firebase."""
        return {
            "steps": [
                {"id": 1, "question": "Qual é o seu nome completo?"},
                {"id": 2, "question": "Qual o seu telefone/WhatsApp e e-mail?"},
                {"id": 3, "question": "Em qual área você precisa de ajuda? Penal ou Saúde (liminares)?"},
                {"id": 4, "question": "Descreva sua situação:"},
                {"id": 5, "question": "Posso direcioná-lo para nosso especialista?"}
            ],
            "completion_message": "Perfeito! Nossa equipe entrará em contato em breve."
        }

    def _get_question_for_step(self, steps: List[Dict], step_number: int) -> str:
        """Obter pergunta para step específico."""
        for step in steps:
            if step.get("id") == step_number:
                return step.get("question", f"Pergunta {step_number}")
        return f"Pergunta {step_number}"

    def _personalize_question(self, question: str, lead_data: Dict[str, Any]) -> str:
        """Personalizar pergunta com dados do lead."""
        try:
            # Substituir placeholders
            if "{user_name}" in question and "step_1" in lead_data:
                name = lead_data["step_1"].split()[0]  # Primeiro nome
                question = question.replace("{user_name}", name)
            
            if "{area}" in question and "step_3" in lead_data:
                question = question.replace("{area}", lead_data["step_3"])
            
            return question
        except Exception:
            return question

    def _validate_and_normalize_answer(self, answer: str, step_id: int) -> Optional[str]:
        """
        ✅ VALIDAR E NORMALIZAR RESPOSTA
        
        Aplica validações específicas por step e normaliza dados brasileiros
        """
        if not answer or len(answer.strip()) < 2:
            return None
        
        answer = answer.strip()
        
        # ✅ STEP 1: NOME COMPLETO
        if step_id == 1:
            if len(answer.split()) < 2:
                return None
            return answer.title()
        
        # ✅ STEP 2: CONTATO (TELEFONE + EMAIL)
        elif step_id == 2:
            # Deve conter pelo menos um número de telefone
            phone_pattern = r'(\d{10,11})'
            if not re.search(phone_pattern, answer):
                return None
            return answer
        
        # ✅ STEP 3: ÁREA JURÍDICA
        elif step_id == 3:
            area_map = {
                "penal": "Direito Penal",
                "criminal": "Direito Penal",
                "crime": "Direito Penal",
                "saude": "Saúde/Liminares",
                "saúde": "Saúde/Liminares",
                "liminar": "Saúde/Liminares",
                "liminares": "Saúde/Liminares",
                "medica": "Saúde/Liminares",
                "médica": "Saúde/Liminares"
            }
            
            answer_lower = answer.lower()
            for key, normalized in area_map.items():
                if key in answer_lower:
                    return normalized
            
            # Se não encontrou mapeamento, aceitar resposta original
            return answer
        
        # ✅ STEP 4: SITUAÇÃO
        elif step_id == 4:
            if len(answer) < 10:
                return None
            return answer
        
        # ✅ STEP 5: CONFIRMAÇÃO
        elif step_id == 5:
            positive_words = ["sim", "yes", "ok", "pode", "quero", "aceito", "concordo"]
            if any(word in answer.lower() for word in positive_words):
                return "Sim"
            return answer
        
        # ✅ DEFAULT: ACEITAR RESPOSTA
        return answer

    async def _complete_conversation_flow(
        self, 
        session_data: Dict[str, Any], 
        flow: Dict[str, Any],
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ COMPLETAR FLUXO DE CONVERSA
        """
        try:
            session_id = session_data["session_id"]
            logger.info(f"🎯 [{correlation_id}] Completando fluxo para {session_id}")
            
            # ✅ MARCAR COMO COMPLETADO
            session_data["flow_completed"] = True
            session_data["state"] = "phone_collection"
            
            # ✅ OBTER LEAD_DATA VÁLIDO
            lead_data = self.safe_get_lead_data(session_data)
            
            # ✅ SALVAR LEAD NO FIREBASE
            try:
                lead_id = await asyncio.wait_for(
                    save_lead_data({"answers": [{"step": k, "answer": v} for k, v in lead_data.items()]}),
                    timeout=self.firebase_timeout
                )
                session_data["lead_id"] = lead_id
                logger.info(f"💾 [{correlation_id}] Lead salvo com ID: {lead_id}")
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao salvar lead - continuando")
            except Exception as lead_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar lead: {str(lead_error)}")
            
            # ✅ SALVAR SESSÃO
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao salvar sessão completada")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão: {str(save_error)}")
            
            # ✅ MENSAGEM DE CONCLUSÃO
            completion_message = flow.get("completion_message", "Perfeito! Agora preciso do seu telefone/WhatsApp para que nossa equipe entre em contato.")
            
            return {
                "session_id": session_id,
                "response": f"{completion_message}\n\nPor favor, informe seu telefone/WhatsApp:",
                "response_type": "flow_completed",
                "flow_completed": True,
                "collecting_phone": True,
                "lead_data": lead_data,  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "lead_id": session_data.get("lead_id")
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao completar fluxo: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_data.get("session_id", "unknown"),
                "response": "Obrigado pelas informações! Por favor, informe seu telefone/WhatsApp:",
                "response_type": "completion_fallback",
                "flow_completed": True,
                "collecting_phone": True,
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE VÁLIDO
                "error": str(e)
            }

    async def _handle_phone_collection(
        self, 
        session_id: str, 
        session_data: Dict[str, Any], 
        phone_message: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        ✅ COLETAR TELEFONE E ENVIAR WHATSAPP
        """
        try:
            logger.info(f"📱 [{correlation_id}] Coletando telefone para {session_id}")
            
            # ✅ VALIDAR TELEFONE
            phone_clean = self._extract_phone_number(phone_message)
            
            if not phone_clean:
                return {
                    "session_id": session_id,
                    "response": "Por favor, informe um número de telefone válido (com DDD):",
                    "response_type": "phone_validation_error",
                    "collecting_phone": True,
                    "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE VÁLIDO
                    "validation_error": True
                }
            
            # ✅ SALVAR TELEFONE
            session_data["phone_submitted"] = True
            session_data["phone_number"] = phone_clean
            session_data["state"] = "completed"
            
            lead_data = self.safe_get_lead_data(session_data)
            lead_data["phone"] = phone_clean
            session_data["lead_data"] = lead_data
            
            logger.info(f"📱 [{correlation_id}] Telefone coletado: {phone_clean}")
            
            # ✅ ENVIAR MENSAGENS WHATSAPP (NÃO BLOQUEAR RESPOSTA)
            asyncio.create_task(self._send_whatsapp_messages(session_data, correlation_id))
            
            # ✅ SALVAR SESSÃO
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, session_data),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao salvar sessão com telefone")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão: {str(save_error)}")
            
            # ✅ RESPOSTA IMEDIATA
            return {
                "session_id": session_id,
                "response": f"✅ Telefone confirmado: {phone_clean}\n\nObrigado! Nossa equipe entrará em contato em breve via WhatsApp. Suas informações foram registradas com sucesso.",
                "response_type": "phone_collected_fallback",
                "flow_completed": True,
                "phone_submitted": True,
                "phone_number": phone_clean,
                "lead_data": lead_data,  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "whatsapp_sending": True
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro na coleta de telefone: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "response": "Obrigado! Nossa equipe entrará em contato em breve.",
                "response_type": "phone_collection_fallback",
                "flow_completed": True,
                "phone_submitted": True,
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE VÁLIDO
                "error": str(e)
            }

    def _extract_phone_number(self, text: str) -> Optional[str]:
        """Extrair número de telefone brasileiro do texto."""
        # Remove tudo exceto dígitos
        digits = re.sub(r'[^\d]', '', text)
        
        # Validar formato brasileiro
        if len(digits) == 11 and digits.startswith(('11', '12', '13', '14', '15', '16', '17', '18', '19', '21', '22', '24', '27', '28')):
            return f"55{digits}"
        elif len(digits) == 10 and digits.startswith(('11', '12', '13', '14', '15', '16', '17', '18', '19', '21', '22', '24', '27', '28')):
            return f"55{digits}"
        elif len(digits) == 13 and digits.startswith("55"):
            return digits
        
        return None

    async def _send_whatsapp_messages(self, session_data: Dict[str, Any], correlation_id: str):
        """
        ✅ ENVIAR MENSAGENS WHATSAPP (BACKGROUND TASK)
        
        Não bloqueia a resposta principal - executa em background
        """
        try:
            phone_number = session_data.get("phone_number")
            lead_data = self.safe_get_lead_data(session_data)
            
            if not phone_number:
                logger.error(f"❌ [{correlation_id}] Telefone não encontrado para envio WhatsApp")
                return
            
            # ✅ TIMEOUT GLOBAL PARA WHATSAPP
            try:
                await asyncio.wait_for(
                    self._send_whatsapp_messages_internal(phone_number, lead_data, correlation_id),
                    timeout=25  # Timeout global para todas as mensagens WhatsApp
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout global no envio WhatsApp")
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no envio WhatsApp: {str(e)}")

    async def _send_whatsapp_messages_internal(self, phone_number: str, lead_data: Dict[str, Any], correlation_id: str):
        """Envio interno das mensagens WhatsApp."""
        try:
            # ✅ MENSAGEM PARA O USUÁRIO
            user_name = lead_data.get("step_1", "Cliente")
            user_message = f"Olá {user_name}! 👋\n\nObrigado por entrar em contato com o m.lima. Recebemos suas informações e nossa equipe especializada entrará em contato em breve.\n\nFique tranquilo, você está em boas mãos! 🤝"
            
            # ✅ ENVIAR PARA USUÁRIO (TIMEOUT INDIVIDUAL)
            try:
                user_success = await asyncio.wait_for(
                    baileys_service.send_whatsapp_message(phone_number, user_message),
                    timeout=self.whatsapp_timeout
                )
                
                if user_success:
                    logger.info(f"✅ [{correlation_id}] Mensagem enviada para usuário: {phone_number}")
                else:
                    logger.error(f"❌ [{correlation_id}] Falha ao enviar para usuário: {phone_number}")
                    
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao enviar WhatsApp para usuário")
            except Exception as user_error:
                logger.error(f"❌ [{correlation_id}] Erro ao enviar para usuário: {str(user_error)}")
            
            # ✅ NOTIFICAR ADVOGADOS (TIMEOUT INDIVIDUAL)
            try:
                await asyncio.wait_for(
                    self._notify_lawyers_background(lead_data, correlation_id),
                    timeout=15  # Timeout para notificações
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao notificar advogados")
            except Exception as lawyer_error:
                logger.error(f"❌ [{correlation_id}] Erro ao notificar advogados: {str(lawyer_error)}")
                
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no envio interno WhatsApp: {str(e)}")

    async def _notify_lawyers_background(self, lead_data: Dict[str, Any], correlation_id: str):
        """Notificar advogados em background."""
        try:
            logger.info(f"🚨 [{correlation_id}] Notificando advogados sobre novo lead")
            
            # ✅ PREPARAR DADOS PARA NOTIFICAÇÃO
            lead_name = lead_data.get("step_1", "Cliente não identificado")
            lead_phone = lead_data.get("phone", "Telefone não informado")
            lead_area = lead_data.get("step_3", "Área não informada")
            
            # ✅ ENVIAR NOTIFICAÇÃO (NÃO PROPAGAR ERRO)
            try:
                result = await lawyer_notification_service.notify_lawyers_of_new_lead(
                    lead_name=lead_name,
                    lead_phone=lead_phone,
                    category=lead_area,
                    additional_info=lead_data
                )
                
                if result.get("success"):
                    logger.info(f"✅ [{correlation_id}] Advogados notificados com sucesso")
                else:
                    logger.error(f"❌ [{correlation_id}] Falha na notificação: {result.get('error', 'unknown')}")
                    
            except Exception as notify_error:
                logger.error(f"❌ [{correlation_id}] Erro na notificação de advogados: {str(notify_error)}")
                # ✅ NÃO PROPAGAR ERRO - APENAS LOGAR
                
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no background de notificação: {str(e)}")

    async def _auto_restart_session(self, session_id: str, message: str, correlation_id: str) -> Dict[str, Any]:
        """
        ✅ AUTO-REINICIAR SESSÃO FINALIZADA
        
        Remove o problema do chat "finalizado" permanente
        """
        try:
            logger.info(f"🔄 [{correlation_id}] Auto-reiniciando sessão finalizada: {session_id}")
            
            # ✅ CRIAR NOVA SESSÃO LIMPA
            new_session_data = {
                "session_id": session_id,
                "platform": "web",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "current_step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "state": "active",
                "message_count": 1,
                "lead_data": {},  # ✅ SEMPRE INICIALIZAR COMO DICT VAZIO
                "correlation_id": correlation_id,
                "restarted": True
            }
            
            # ✅ SALVAR NOVA SESSÃO
            try:
                await asyncio.wait_for(
                    save_user_session(session_id, new_session_data),
                    timeout=self.firebase_timeout
                )
                logger.info(f"✅ [{correlation_id}] Sessão reiniciada e salva: {session_id}")
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao salvar sessão reiniciada")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar sessão reiniciada: {str(save_error)}")
            
            # ✅ PROCESSAR MENSAGEM NA NOVA SESSÃO
            return await self.process_message(message, session_id, platform="web")
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no auto-restart: {str(e)}")
            
            # ✅ FALLBACK SEGURO
            return {
                "session_id": session_id,
                "response": self._get_personalized_greeting(),
                "response_type": "auto_restart_fallback",
                "current_step": 1,
                "flow_completed": False,
                "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                "restarted": True,
                "error": str(e)
            }

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        ✅ OBTER CONTEXTO DA SESSÃO COM VALIDAÇÃO
        """
        try:
            correlation_id = f"ctx_{uuid.uuid4().hex[:8]}"
            logger.info(f"📊 [{correlation_id}] Obtendo contexto da sessão: {session_id}")
            
            # ✅ BUSCAR SESSÃO
            try:
                session_data = await asyncio.wait_for(
                    get_user_session(session_id),
                    timeout=self.firebase_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [{correlation_id}] Timeout ao buscar contexto")
                session_data = None
            except Exception as e:
                logger.error(f"❌ [{correlation_id}] Erro ao buscar contexto: {str(e)}")
                session_data = None
            
            if not session_data:
                # ✅ SESSÃO NÃO ENCONTRADA - RETORNAR PADRÃO
                return {
                    "session_id": session_id,
                    "status_info": {
                        "step": 1,
                        "flow_completed": False,
                        "phone_submitted": False,
                        "state": "new"
                    },
                    "lead_data": {},  # ✅ SEMPRE RETORNAR LEAD_DATA VÁLIDO
                    "current_step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "correlation_id": correlation_id
                }
            
            # ✅ GARANTIR INTEGRIDADE
            session_data = await self._ensure_session_integrity(session_id, session_data)
            
            # ✅ RETORNAR CONTEXTO COMPLETO
            return {
                "session_id": session_id,
                "status_info": {
                    "step": session_data.get("current_step", 1),
                    "flow_completed": session_data.get("flow_completed", False),
                    "phone_submitted": session_data.get("phone_submitted", False),
                    "state": session_data.get("state", "active"),
                    "message_count": session_data.get("message_count", 0)
                },
                "lead_data": self.safe_get_lead_data(session_data),  # ✅ SEMPRE VÁLIDO
                "current_step": session_data.get("current_step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "gemini_available": session_data.get("gemini_available", True),
                "platform": session_data.get("platform", "web"),
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter contexto da sessão {session_id}: {str(e)}")
            
            # ✅ FALLBACK SEGURO
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
        """Obter status geral dos serviços."""
        try:
            return {
                "overall_status": "operational",
                "gemini_available": self.gemini_available,
                "firebase_status": "active",
                "ai_status": "active" if self.gemini_available else "fallback_mode",
                "fallback_mode": not self.gemini_available,
                "last_gemini_check": self.last_gemini_check.isoformat(),
                "timeouts": {
                    "gemini": f"{self.gemini_timeout}s",
                    "whatsapp": f"{self.whatsapp_timeout}s", 
                    "firebase": f"{self.firebase_timeout}s"
                }
            }
        except Exception as e:
            logger.error(f"❌ Erro ao obter status geral: {str(e)}")
            return {
                "overall_status": "degraded",
                "error": str(e),
                "fallback_mode": True
            }

    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]):
        """Handle WhatsApp authorization from landing page."""
        try:
            session_id = auth_data.get("session_id")
            logger.info(f"🔐 Handling WhatsApp authorization for session: {session_id}")
            
            # This is handled by the WhatsApp routes
            # Just log for now
            logger.info(f"✅ WhatsApp authorization processed for {session_id}")
            
        except Exception as e:
            logger.error(f"❌ Error handling WhatsApp authorization: {str(e)}")


# ✅ INSTÂNCIA GLOBAL DO ORQUESTRADOR
intelligent_orchestrator = IntelligentHybridOrchestrator()

logger.info("🚀 Intelligent Hybrid Orchestrator loaded - PRODUCTION READY")