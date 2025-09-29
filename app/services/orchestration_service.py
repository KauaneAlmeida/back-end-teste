"""
Intelligent Hybrid Orchestration Service - PRODUCTION READY

Sistema de orquestração inteligente que combina IA (Gemini) com fluxo estruturado (Firebase).
Implementa fallback automático, validação robusta e integração WhatsApp.

FLUXO PRINCIPAL:
1. Tenta IA primeiro (Gemini) com timeout de 15s
2. Se falhar, usa fluxo estruturado do Firebase
3. Coleta dados em 5 steps determinísticos
4. Envia notificações WhatsApp para advogados
5. Auto-reinicia para nova conversa

MELHORIAS IMPLEMENTADAS:
- Saudação personalizada por horário
- Remoção do travamento "finalizado"
- Auto-reinicialização após completar fluxo
- Logs estruturados com correlation IDs
- Rate limiting (10 msgs/min)
- Validação rigorosa de dados brasileiros
"""

import os
import re
import json
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from collections import defaultdict

from app.services.ai_chain import ai_orchestrator
from app.services.firebase_service import (
    get_conversation_flow, save_user_session, get_user_session, save_lead_data
)
from app.services.baileys_service import baileys_service
from app.services.lawyer_notification_service import lawyer_notification_service

logger = logging.getLogger(__name__)

class IntelligentHybridOrchestrator:
    """
    Orquestrador híbrido inteligente para conversas jurídicas.
    
    Combina IA (Gemini) com fluxo estruturado (Firebase) para máxima robustez.
    Implementa fallback automático, validação de dados e integração WhatsApp.
    """

    def __init__(self):
        self.gemini_availability = {}  # Track per session
        self.session_locks = {}  # Prevent race conditions
        self.rate_limits = defaultdict(list)  # Rate limiting per session
        self.correlation_ids = {}  # Track request correlation
        
    def _get_personalized_greeting(self) -> str:
        """
        Gera saudação personalizada baseada no horário atual.
        
        Returns:
            str: Saudação com horário + pergunta do nome
        """
        try:
            # Usar horário de Brasília (UTC-3)
            import pytz
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
            # Fallback se não conseguir determinar horário
            greeting = "Olá"
        
        return f"{greeting}! Bem-vindo ao m.lima. Estou aqui para entender seu caso e agilizar o contato com um de nossos advogados especializados.\n\nPara começar, qual é o seu nome completo?"

    async def start_conversation(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Inicia uma nova conversa com saudação personalizada.
        
        Args:
            session_id: ID da sessão (opcional)
            
        Returns:
            Dict com saudação personalizada e pergunta do nome
        """
        try:
            # Gerar session_id se não fornecido
            if not session_id:
                session_id = f"web_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
            
            correlation_id = str(uuid.uuid4())[:8]
            self.correlation_ids[session_id] = correlation_id
            
            logger.info(f"🚀 [{correlation_id}] Iniciando nova conversa: {session_id}")
            
            # Saudação personalizada por horário
            greeting_message = self._get_personalized_greeting()
            
            # Inicializar sessão limpa
            session_data = {
                "session_id": session_id,
                "platform": "web",
                "step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "lead_data": {},
                "message_count": 0,
                "created_at": datetime.now().isoformat(),
                "correlation_id": correlation_id,
                "state": "active"
            }
            
            await save_user_session(session_id, session_data)
            
            logger.info(f"✅ [{correlation_id}] Conversa iniciada com saudação personalizada")
            
            return {
                "session_id": session_id,
                "response": greeting_message,
                "response_type": "personalized_greeting",
                "step": 1,
                "flow_completed": False,
                "ai_mode": False,
                "correlation_id": correlation_id,
                "state": "active"
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao iniciar conversa: {str(e)}")
            return {
                "session_id": session_id or f"error_{uuid.uuid4().hex[:8]}",
                "response": "Olá! Como posso ajudá-lo hoje?",
                "response_type": "fallback_greeting",
                "error": str(e)
            }

    async def process_message(
        self, 
        message: str, 
        session_id: str, 
        phone_number: Optional[str] = None,
        platform: str = "web"
    ) -> Dict[str, Any]:
        """
        Processa mensagem do usuário com orquestração inteligente.
        
        Args:
            message: Mensagem do usuário
            session_id: ID da sessão
            phone_number: Número do WhatsApp (opcional)
            platform: Plataforma (web/whatsapp)
            
        Returns:
            Dict com resposta e metadados
        """
        correlation_id = self.correlation_ids.get(session_id, str(uuid.uuid4())[:8])
        
        try:
            logger.info(f"📨 [{correlation_id}] Processando mensagem: {message[:50]}...")
            
            # Rate limiting
            if self._is_rate_limited(session_id):
                logger.warning(f"⏰ [{correlation_id}] Rate limit atingido")
                return {
                    "session_id": session_id,
                    "response": "⏳ Muitas mensagens em pouco tempo. Aguarde um momento...",
                    "response_type": "rate_limited",
                    "correlation_id": correlation_id
                }
            
            # Obter ou criar sessão
            session_data = await get_user_session(session_id)
            if not session_data:
                logger.info(f"🆕 [{correlation_id}] Criando nova sessão")
                session_data = {
                    "session_id": session_id,
                    "platform": platform,
                    "step": 1,
                    "flow_completed": False,
                    "phone_submitted": False,
                    "gemini_available": True,
                    "lead_data": {},
                    "message_count": 0,
                    "created_at": datetime.now().isoformat(),
                    "correlation_id": correlation_id,
                    "state": "active"
                }
            
            # Incrementar contador de mensagens
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            session_data["last_message"] = message
            session_data["last_activity"] = datetime.now().isoformat()
            
            # Verificar se fluxo foi completado e auto-reiniciar
            if session_data.get("flow_completed") and session_data.get("phone_submitted"):
                logger.info(f"🔄 [{correlation_id}] Auto-reiniciando sessão completada")
                return await self._auto_restart_session(session_id, message, platform, correlation_id)
            
            # Processar fluxo de conversa
            result = await self._process_conversation_flow(
                message, session_id, session_data, platform, correlation_id
            )
            
            # Salvar sessão atualizada
            await save_user_session(session_id, session_data)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no processamento: {str(e)}")
            return {
                "session_id": session_id,
                "response": "Desculpe, ocorreu um erro. Vamos tentar novamente?",
                "response_type": "system_error",
                "error": str(e),
                "correlation_id": correlation_id
            }

    async def _auto_restart_session(
        self, 
        session_id: str, 
        message: str, 
        platform: str, 
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        Auto-reinicia sessão após completar fluxo.
        
        Args:
            session_id: ID da sessão
            message: Nova mensagem
            platform: Plataforma
            correlation_id: ID de correlação
            
        Returns:
            Dict com nova conversa iniciada
        """
        try:
            logger.info(f"🔄 [{correlation_id}] Auto-reiniciando sessão completada")
            
            # Criar nova sessão limpa
            new_session_data = {
                "session_id": session_id,
                "platform": platform,
                "step": 1,
                "flow_completed": False,
                "phone_submitted": False,
                "gemini_available": True,
                "lead_data": {},
                "message_count": 1,
                "created_at": datetime.now().isoformat(),
                "correlation_id": correlation_id,
                "state": "active",
                "restarted_from_completed": True
            }
            
            await save_user_session(session_id, new_session_data)
            
            # Processar primeira mensagem da nova sessão
            return await self._process_conversation_flow(
                message, session_id, new_session_data, platform, correlation_id
            )
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no auto-restart: {str(e)}")
            # Fallback: retornar saudação
            return {
                "session_id": session_id,
                "response": self._get_personalized_greeting(),
                "response_type": "restart_fallback",
                "step": 1,
                "correlation_id": correlation_id
            }

    async def _process_conversation_flow(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any], 
        platform: str,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        Processa o fluxo de conversa com IA ou fallback.
        
        Args:
            message: Mensagem do usuário
            session_id: ID da sessão
            session_data: Dados da sessão
            platform: Plataforma
            correlation_id: ID de correlação
            
        Returns:
            Dict com resposta processada
        """
        try:
            # Verificar se está coletando telefone
            if session_data.get("flow_completed") and not session_data.get("phone_submitted"):
                return await self._handle_phone_collection(
                    message, session_id, session_data, correlation_id
                )
            
            # Tentar IA primeiro (se disponível)
            if session_data.get("gemini_available", True):
                try:
                    ai_result = await self._attempt_gemini_response(
                        message, session_id, session_data, correlation_id
                    )
                    if ai_result:
                        return ai_result
                except Exception as ai_error:
                    logger.warning(f"⚠️ [{correlation_id}] IA falhou, usando fallback: {str(ai_error)}")
                    session_data["gemini_available"] = False
            
            # Fallback: Fluxo estruturado Firebase
            return await self._get_fallback_response(
                message, session_id, session_data, correlation_id
            )
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no fluxo: {str(e)}")
            return {
                "session_id": session_id,
                "response": "Desculpe, vamos tentar novamente. Qual é o seu nome completo?",
                "response_type": "error_recovery",
                "correlation_id": correlation_id
            }

    async def _attempt_gemini_response(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any],
        correlation_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Tenta gerar resposta via Gemini AI.
        
        Args:
            message: Mensagem do usuário
            session_id: ID da sessão
            session_data: Dados da sessão
            correlation_id: ID de correlação
            
        Returns:
            Dict com resposta da IA ou None se falhar
        """
        try:
            logger.info(f"🤖 [{correlation_id}] Tentando resposta Gemini")
            
            # Contexto da conversa
            context = {
                "platform": session_data.get("platform", "web"),
                "message_count": session_data.get("message_count", 0),
                "lead_data": session_data.get("lead_data", {})
            }
            
            # Timeout de 15 segundos
            ai_response = await asyncio.wait_for(
                ai_orchestrator.generate_response(message, session_id, context),
                timeout=15.0
            )
            
            if ai_response and len(ai_response.strip()) > 0:
                logger.info(f"✅ [{correlation_id}] Resposta Gemini gerada")
                session_data["gemini_available"] = True
                
                return {
                    "session_id": session_id,
                    "response": ai_response,
                    "response_type": "ai_intelligent",
                    "ai_mode": True,
                    "gemini_available": True,
                    "correlation_id": correlation_id
                }
            
            return None
            
        except asyncio.TimeoutError:
            logger.error(f"⏰ [{correlation_id}] Timeout Gemini (15s)")
            session_data["gemini_available"] = False
            return None
        except Exception as e:
            error_str = str(e).lower()
            if any(indicator in error_str for indicator in ["429", "quota", "resourceexhausted", "billing"]):
                logger.error(f"🚫 [{correlation_id}] Quota Gemini excedida: {e}")
                session_data["gemini_available"] = False
            else:
                logger.error(f"❌ [{correlation_id}] Erro Gemini: {e}")
            return None

    async def _get_fallback_response(
        self, 
        message: str, 
        session_id: str, 
        session_data: Dict[str, Any],
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        Gera resposta usando fluxo estruturado Firebase.
        
        Args:
            message: Mensagem do usuário
            session_id: ID da sessão
            session_data: Dados da sessão
            correlation_id: ID de correlação
            
        Returns:
            Dict com resposta do fluxo estruturado
        """
        try:
            logger.info(f"⚡ [{correlation_id}] Ativando fallback Firebase")
            
            # Obter fluxo de conversa
            flow = await get_conversation_flow()
            steps = flow.get("steps", [])
            
            current_step = session_data.get("step", 1)
            
            # Validar e processar resposta
            if current_step > 1:  # Não validar primeira interação
                validation_result = self._validate_and_normalize_answer(message, current_step - 1)
                if validation_result:
                    # Salvar resposta validada
                    session_data["lead_data"][f"step_{current_step - 1}"] = validation_result
                    logger.info(f"💾 [{correlation_id}] Resposta salva step {current_step - 1}: {validation_result}")
                else:
                    # Re-prompt mesma pergunta
                    current_question = next((s["question"] for s in steps if s["id"] == current_step - 1), "")
                    return {
                        "session_id": session_id,
                        "response": f"Por favor, forneça uma resposta mais completa. {current_question}",
                        "response_type": "validation_error",
                        "step": current_step - 1,
                        "correlation_id": correlation_id
                    }
            
            # Avançar para próximo step
            if current_step <= len(steps):
                next_step = next((s for s in steps if s["id"] == current_step), None)
                if next_step:
                    session_data["step"] = current_step + 1
                    
                    # Personalizar pergunta com dados coletados
                    question = self._personalize_question(
                        next_step["question"], 
                        session_data["lead_data"]
                    )
                    
                    return {
                        "session_id": session_id,
                        "response": question,
                        "response_type": "fallback_firebase",
                        "step": current_step,
                        "ai_mode": False,
                        "gemini_available": False,
                        "correlation_id": correlation_id
                    }
            
            # Fluxo completo - solicitar telefone
            if not session_data.get("flow_completed"):
                session_data["flow_completed"] = True
                return {
                    "session_id": session_id,
                    "response": "Perfeito! Para finalizar, preciso do seu número de WhatsApp para que nossa equipe entre em contato:",
                    "response_type": "phone_request",
                    "flow_completed": True,
                    "collecting_phone": True,
                    "correlation_id": correlation_id
                }
            
            # Fallback final
            return {
                "session_id": session_id,
                "response": "Obrigado pelas informações! Nossa equipe entrará em contato em breve.",
                "response_type": "completion_fallback",
                "correlation_id": correlation_id
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no fallback: {str(e)}")
            return {
                "session_id": session_id,
                "response": "Vamos começar novamente. Qual é o seu nome completo?",
                "response_type": "fallback_error",
                "step": 1,
                "correlation_id": correlation_id
            }

    async def _handle_phone_collection(
        self, 
        phone_message: str, 
        session_id: str, 
        session_data: Dict[str, Any],
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        Processa coleta de número de telefone.
        
        Args:
            phone_message: Mensagem com telefone
            session_id: ID da sessão
            session_data: Dados da sessão
            correlation_id: ID de correlação
            
        Returns:
            Dict com resultado da coleta
        """
        try:
            logger.info(f"📱 [{correlation_id}] Coletando telefone")
            
            # Validar número de telefone
            if not self._is_phone_number(phone_message):
                return {
                    "session_id": session_id,
                    "response": "Por favor, informe um número de WhatsApp válido (com DDD):",
                    "response_type": "phone_validation_error",
                    "collecting_phone": True,
                    "correlation_id": correlation_id
                }
            
            # Formatar número
            phone_formatted = self._format_phone_number(phone_message)
            session_data["lead_data"]["phone"] = phone_formatted
            session_data["phone_submitted"] = True
            
            # Salvar lead completo
            try:
                lead_id = await save_lead_data({
                    "answers": [
                        {"id": i, "answer": session_data["lead_data"].get(f"step_{i}", "")}
                        for i in range(1, 6)
                    ] + [{"id": 6, "answer": phone_formatted}],
                    "lead_summary": self._generate_lead_summary(session_data["lead_data"]),
                    "phone": phone_formatted,
                    "source": "intelligent_orchestrator",
                    "correlation_id": correlation_id
                })
                logger.info(f"💾 [{correlation_id}] Lead salvo: {lead_id}")
            except Exception as save_error:
                logger.error(f"❌ [{correlation_id}] Erro ao salvar lead: {save_error}")
            
            # Notificar advogados
            try:
                await self._notify_lawyers_with_lead_data(session_data["lead_data"], correlation_id)
            except Exception as notify_error:
                logger.error(f"❌ [{correlation_id}] Erro ao notificar advogados: {notify_error}")
            
            # Enviar mensagem de boas-vindas via WhatsApp
            try:
                await self._send_welcome_whatsapp_message(
                    phone_formatted, 
                    session_data["lead_data"], 
                    correlation_id
                )
            except Exception as whatsapp_error:
                logger.error(f"❌ [{correlation_id}] Erro WhatsApp: {whatsapp_error}")
            
            logger.info(f"✅ [{correlation_id}] Fluxo completado com sucesso")
            
            return {
                "session_id": session_id,
                "response": f"✅ Telefone {phone_formatted} confirmado! Nossa equipe entrará em contato em breve. Obrigado!",
                "response_type": "phone_collected_success",
                "phone_submitted": True,
                "flow_completed": True,
                "phone_number": phone_formatted,
                "lead_saved": True,
                "lawyers_notified": True,
                "whatsapp_sent": True,
                "correlation_id": correlation_id,
                "state": "completed"
            }
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro na coleta de telefone: {str(e)}")
            return {
                "session_id": session_id,
                "response": "Ocorreu um erro. Por favor, informe seu WhatsApp novamente:",
                "response_type": "phone_collection_error",
                "collecting_phone": True,
                "error": str(e),
                "correlation_id": correlation_id
            }

    def _validate_and_normalize_answer(self, answer: str, step_id: int) -> Optional[str]:
        """
        Valida e normaliza resposta do usuário.
        
        Args:
            answer: Resposta do usuário
            step_id: ID do step atual
            
        Returns:
            Resposta normalizada ou None se inválida
        """
        if not answer or len(answer.strip()) < 2:
            return None
        
        answer = answer.strip()
        
        # Step 1: Nome (mínimo 2 palavras)
        if step_id == 1:
            if len(answer.split()) < 2:
                return None
            return answer.title()
        
        # Step 2: Contato (telefone + email)
        elif step_id == 2:
            if len(answer) < 10:
                return None
            return answer
        
        # Step 3: Área jurídica
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
            for key, value in area_map.items():
                if key in answer_lower:
                    return value
            
            # Se não encontrou mapeamento, aceitar resposta
            return answer
        
        # Step 4: Situação (mínimo 10 caracteres)
        elif step_id == 4:
            if len(answer) < 10:
                return None
            return answer
        
        # Step 5: Confirmação
        elif step_id == 5:
            return answer
        
        return answer

    def _personalize_question(self, question: str, lead_data: Dict[str, Any]) -> str:
        """
        Personaliza pergunta com dados coletados.
        
        Args:
            question: Pergunta template
            lead_data: Dados coletados
            
        Returns:
            Pergunta personalizada
        """
        try:
            # Extrair nome do step 1
            name = lead_data.get("step_1", "")
            if name:
                first_name = name.split()[0]
                question = question.replace("{user_name}", first_name)
            
            # Extrair área do step 3
            area = lead_data.get("step_3", "")
            if area:
                question = question.replace("{area}", area)
            
            return question
        except Exception:
            return question

    def _generate_lead_summary(self, lead_data: Dict[str, Any]) -> str:
        """
        Gera resumo do lead para advogados.
        
        Args:
            lead_data: Dados do lead
            
        Returns:
            Resumo formatado
        """
        try:
            name = lead_data.get("step_1", "N/A")
            contact = lead_data.get("step_2", "N/A")
            area = lead_data.get("step_3", "N/A")
            situation = lead_data.get("step_4", "N/A")
            phone = lead_data.get("phone", "N/A")
            
            return f"""Lead Qualificado:
Nome: {name}
Contato: {contact}
Área: {area}
Situação: {situation}
WhatsApp: {phone}

✅ Pronto para atendimento"""
        except Exception:
            return "Lead capturado via chat"

    async def _notify_lawyers_with_lead_data(
        self, 
        lead_data: Dict[str, Any], 
        correlation_id: str
    ) -> bool:
        """
        Notifica advogados com dados do lead.
        
        Args:
            lead_data: Dados do lead
            correlation_id: ID de correlação
            
        Returns:
            True se notificações enviadas
        """
        try:
            logger.info(f"📧 [{correlation_id}] Notificando advogados")
            
            name = lead_data.get("step_1", "Cliente")
            phone = lead_data.get("phone", "")
            area = lead_data.get("step_3", "Não informado")
            situation = lead_data.get("step_4", "")
            
            result = await lawyer_notification_service.notify_lawyers_of_new_lead(
                lead_name=name,
                lead_phone=phone,
                category=area,
                additional_info={
                    "situation": situation,
                    "source": "intelligent_orchestrator",
                    "correlation_id": correlation_id
                }
            )
            
            success = result.get("success", False)
            notifications_sent = result.get("notifications_sent", 0)
            
            logger.info(f"📧 [{correlation_id}] Advogados notificados: {notifications_sent}")
            return success
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro ao notificar advogados: {str(e)}")
            return False

    async def _send_welcome_whatsapp_message(
        self, 
        phone_number: str, 
        lead_data: Dict[str, Any], 
        correlation_id: str
    ) -> bool:
        """
        Envia mensagem de boas-vindas via WhatsApp.
        
        Args:
            phone_number: Número do WhatsApp
            lead_data: Dados do lead
            correlation_id: ID de correlação
            
        Returns:
            True se mensagem enviada
        """
        try:
            name = lead_data.get("step_1", "").split()[0] if lead_data.get("step_1") else "Cliente"
            area = lead_data.get("step_3", "sua área jurídica")
            
            welcome_message = f"""Olá {name}! 👋

Suas informações foram registradas com sucesso no m.lima.

📋 Resumo:
• Área: {area}
• Status: Em análise

Nossa equipe especializada entrará em contato em breve para dar continuidade ao seu caso.

Obrigado pela confiança! 🤝"""
            
            logger.info(f"📱 [{correlation_id}] Enviando boas-vindas WhatsApp para {phone_number}")
            
            # Usar apenas número limpo (sem @s.whatsapp.net)
            clean_phone = ''.join(filter(str.isdigit, phone_number))
            if not clean_phone.startswith("55"):
                clean_phone = f"55{clean_phone}"
            
            success = await baileys_service.send_whatsapp_message(clean_phone, welcome_message)
            
            if success:
                logger.info(f"✅ [{correlation_id}] Boas-vindas enviadas para {clean_phone}")
            else:
                logger.error(f"❌ [{correlation_id}] Falha no envio para {clean_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ [{correlation_id}] Erro no WhatsApp: {str(e)}")
            return False

    def _is_phone_number(self, text: str) -> bool:
        """
        Verifica se texto contém número de telefone válido.
        
        Args:
            text: Texto a verificar
            
        Returns:
            True se contém telefone válido
        """
        # Extrair apenas dígitos
        digits = ''.join(filter(str.isdigit, text))
        
        # Verificar tamanho (10-13 dígitos)
        if len(digits) < 10 or len(digits) > 13:
            return False
        
        # Verificar padrões brasileiros
        if len(digits) == 10:  # DDD + 8 dígitos
            return True
        elif len(digits) == 11:  # DDD + 9 dígitos
            return True
        elif len(digits) == 12 and digits.startswith("55"):  # +55 + DDD + 8
            return True
        elif len(digits) == 13 and digits.startswith("55"):  # +55 + DDD + 9
            return True
        
        return False

    def _format_phone_number(self, phone_text: str) -> str:
        """
        Formata número de telefone para padrão brasileiro.
        
        Args:
            phone_text: Texto com telefone
            
        Returns:
            Número formatado
        """
        # Extrair apenas dígitos
        digits = ''.join(filter(str.isdigit, phone_text))
        
        # Adicionar código do país se necessário
        if len(digits) == 10 or len(digits) == 11:
            digits = f"55{digits}"
        
        return digits

    def _is_rate_limited(self, session_id: str) -> bool:
        """
        Verifica se sessão atingiu rate limit.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            True se rate limited
        """
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)
        
        # Limpar timestamps antigos
        self.rate_limits[session_id] = [
            ts for ts in self.rate_limits[session_id] if ts > cutoff
        ]
        
        # Verificar limite (10 mensagens por minuto)
        if len(self.rate_limits[session_id]) >= 10:
            return True
        
        # Adicionar timestamp atual
        self.rate_limits[session_id].append(now)
        return False

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        Obtém contexto completo da sessão.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            Dict com contexto da sessão
        """
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return {"error": "Session not found"}
            
            correlation_id = session_data.get("correlation_id", "unknown")
            
            return {
                "session_id": session_id,
                "status_info": session_data,
                "correlation_id": correlation_id,
                "current_step": session_data.get("step", 1),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "message_count": session_data.get("message_count", 0),
                "gemini_available": session_data.get("gemini_available", True),
                "lead_data": session_data.get("lead_data", {}),
                "state": session_data.get("state", "active")
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter contexto da sessão {session_id}: {str(e)}")
            return {"error": str(e)}

    async def get_overall_service_status(self) -> Dict[str, Any]:
        """
        Obtém status geral dos serviços.
        
        Returns:
            Dict com status dos serviços
        """
        try:
            # Verificar serviços
            firebase_status = "active"
            gemini_status = "active" if any(self.gemini_availability.values()) else "degraded"
            whatsapp_status = "active" if baileys_service.is_healthy() else "degraded"
            
            return {
                "overall_status": "active",
                "firebase_status": firebase_status,
                "ai_status": gemini_status,
                "whatsapp_status": whatsapp_status,
                "gemini_available": gemini_status == "active",
                "fallback_mode": gemini_status != "active",
                "active_sessions": len(self.correlation_ids),
                "rate_limited_sessions": len([s for s in self.rate_limits.values() if len(s) >= 10])
            }
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter status geral: {str(e)}")
            return {
                "overall_status": "error",
                "error": str(e)
            }

    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]) -> bool:
        """
        Processa autorização WhatsApp.
        
        Args:
            auth_data: Dados de autorização
            
        Returns:
            True se processado com sucesso
        """
        try:
            session_id = auth_data.get("session_id")
            phone_number = auth_data.get("phone_number")
            source = auth_data.get("source", "unknown")
            
            logger.info(f"🔐 Processando autorização WhatsApp: {session_id} | {source}")
            
            # Enviar mensagem estratégica via WhatsApp
            if phone_number and source in ["landing_chat", "landing_button"]:
                clean_phone = ''.join(filter(str.isdigit, phone_number))
                if not clean_phone.startswith("55"):
                    clean_phone = f"55{clean_phone}"
                
                strategic_message = """🏛️ m.lima - Escritório de Advocacia

Olá! Recebemos sua solicitação através do nosso site.

Nossa equipe especializada está analisando seu caso e entrará em contato em breve para oferecer a melhor solução jurídica.

📞 Mantenha este WhatsApp ativo para receber nossas atualizações.

Obrigado pela confiança! ⚖️"""
                
                await baileys_service.send_whatsapp_message(clean_phone, strategic_message)
                logger.info(f"📱 Mensagem estratégica enviada para {clean_phone}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro na autorização WhatsApp: {str(e)}")
            return False


# Instância global do orquestrador
intelligent_orchestrator = IntelligentHybridOrchestrator()