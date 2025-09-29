import logging
import json
import os
import re
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from app.services.firebase_service import (
    get_user_session,
    save_user_session,
    save_lead_data,
    get_conversation_flow,
    get_firebase_service_status
)
from app.services.ai_chain import ai_orchestrator
from app.services.baileys_service import baileys_service
from app.services.lawyer_notification_service import lawyer_notification_service

logger = logging.getLogger(__name__)


def ensure_utc(dt: datetime) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class IntelligentHybridOrchestrator:
    def __init__(self):
        self.gemini_available = True
        self.gemini_timeout = 15.0
        self.law_firm_number = "+5511918368812"

    def _format_brazilian_phone(self, phone_clean: str) -> str:
        """Format Brazilian phone number correctly for WhatsApp."""
        try:
            if not phone_clean:
                return ""
            phone_clean = ''.join(filter(str.isdigit, str(phone_clean)))

            if phone_clean.startswith("55"):
                phone_clean = phone_clean[2:]

            if len(phone_clean) == 8:
                return f"55{phone_clean}"
            if len(phone_clean) == 9:
                return f"55{phone_clean}"
            if len(phone_clean) == 10:
                ddd = phone_clean[:2]
                number = phone_clean[2:]
                if len(number) == 8 and number[0] in ['6', '7', '8', '9']:
                    number = f"9{number}"
                return f"55{ddd}{number}"
            if len(phone_clean) == 11:
                ddd = phone_clean[:2]
                number = phone_clean[2:]
                return f"55{ddd}{number}"
            return f"55{phone_clean}"
        except Exception as e:
            logger.error(f"Error formatting phone number {phone_clean}: {str(e)}")
            return f"55{phone_clean if phone_clean else ''}"

    def _get_personalized_greeting(self, phone_number: Optional[str] = None, session_id: str = "", user_name: str = "") -> str:
        """Mensagem inicial estratégica otimizada"""
        now = datetime.now()
        hour = now.hour
        
        if 5 <= hour < 12:
            greeting = "Bom dia"
        elif 12 <= hour < 18:
            greeting = "Boa tarde"
        else:
            greeting = "Boa noite"
        
        strategic_greeting = f"""{greeting}! 👋

Bem-vindo ao m.lima Advogados Associados.

Você está no lugar certo! Somos especialistas em Direito Penal e da Saúde, com mais de 1000 casos resolvidos e uma equipe experiente pronta para te ajudar.

💼 Sabemos que questões jurídicas podem ser urgentes e complexas, por isso oferecemos:
• Atendimento ágil e personalizado
• Estratégias focadas em resultados
• Acompanhamento completo do seu caso

Para que eu possa direcionar você ao advogado especialista ideal e acelerar a solução do seu caso, preciso conhecer um pouco mais sobre sua situação.

Qual é o seu nome completo? 😊"""
        
        return strategic_greeting

    def _get_strategic_whatsapp_message(self, user_name: str, area: str, phone_formatted: str) -> str:
        """Mensagem estratégica otimizada para conversão"""
        first_name = user_name.split()[0] if user_name else "Cliente"
        
        area_messages = {
            "penal": {
                "expertise": "Nossa equipe especializada em Direito Penal já resolveu centenas de casos similares",
                "urgency": "Sabemos que situações criminais precisam de atenção IMEDIATA",
                "benefit": "proteger seus direitos e buscar o melhor resultado possível"
            },
            "saude": {
                "expertise": "Nossos advogados especialistas em Direito da Saúde têm expertise em ações contra planos",
                "urgency": "Questões de saúde não podem esperar",
                "benefit": "garantir seu tratamento e obter as coberturas devidas"
            },
            "default": {
                "expertise": "Nossa equipe jurídica experiente",
                "urgency": "Sua situação precisa de atenção especializada",
                "benefit": "alcançar a solução mais eficaz para seu caso"
            }
        }
        
        area_key = "default"
        if any(word in area.lower() for word in ["penal", "criminal", "crime"]):
            area_key = "penal"
        elif any(word in area.lower() for word in ["saude", "saúde", "plano", "medic"]):
            area_key = "saude"
            
        msgs = area_messages[area_key]
        
        strategic_message = f"""🚀 {first_name}, uma EXCELENTE notícia!

✅ Seu atendimento foi PRIORIZADO no sistema m.lima

{msgs['expertise']} com resultados comprovados e já foi IMEDIATAMENTE notificada sobre seu caso.

🎯 {msgs['urgency']} - por isso um advogado experiente entrará em contato com você nos PRÓXIMOS MINUTOS.

🏆 DIFERENCIAL m.lima:
• ⚡ Atendimento ágil e personalizado
• 🎯 Estratégia focada em RESULTADOS
• 📋 Acompanhamento completo do processo
• 💪 Equipe com vasta experiência

Você fez a escolha certa ao confiar no m.lima para {msgs['benefit']}.

⏰ Aguarde nossa ligação - sua situação está em excelentes mãos!

---
✉️ m.lima Advogados Associados
📱 Contato prioritário ativado"""

        return strategic_message

    async def should_notify_lawyers(self, session_data: Dict[str, Any], platform: str) -> Dict[str, Any]:
        """Lógica inteligente de notificação"""
        try:
            if session_data.get("lawyers_notified", False):
                return {
                    "should_notify": False,
                    "reason": "already_notified",
                    "message": "Advogados já foram notificados anteriormente"
                }
            
            lead_data = session_data.get("lead_data", {})
            message_count = session_data.get("message_count", 0)
            current_step = session_data.get("current_step", "")
            flow_completed = session_data.get("flow_completed", False)
            
            if platform == "web":
                required_fields = ["identification", "contact_info", "area_qualification", "case_details"]
                has_required_fields = all(lead_data.get(field) for field in required_fields)
                
                criteria_met = (
                    flow_completed and 
                    has_required_fields and
                    len(lead_data.get("identification", "").strip()) >= 3 and
                    len(lead_data.get("case_details", "").strip()) >= 15
                )
                
                qualification_score = self._calculate_qualification_score(lead_data, platform)
                
                if criteria_met and qualification_score >= 0.8:
                    return {
                        "should_notify": True,
                        "reason": "web_flow_completed",
                        "qualification_score": qualification_score,
                        "message": f"Lead web qualificado - Score: {qualification_score:.2f}"
                    }
                
            elif platform == "whatsapp":
                required_fields = ["identification", "contact_info", "area_qualification"]
                has_required_fields = all(lead_data.get(field) for field in required_fields)
                
                engagement_criteria = (
                    message_count >= 4 and
                    has_required_fields and
                    len(lead_data.get("identification", "").strip()) >= 3 and
                    len(lead_data.get("area_qualification", "").strip()) >= 3
                )
                
                advanced_step = current_step in ["step4_details", "step5_confirmation", "completed"]
                qualification_score = self._calculate_qualification_score(lead_data, platform)
                
                if engagement_criteria and advanced_step and qualification_score >= 0.7:
                    return {
                        "should_notify": True,
                        "reason": "whatsapp_qualified",
                        "qualification_score": qualification_score,
                        "engagement_level": message_count,
                        "current_step": current_step,
                        "message": f"Lead WhatsApp qualificado - Score: {qualification_score:.2f}, Step: {current_step}"
                    }
            
            return {
                "should_notify": False,
                "reason": "not_qualified_yet",
                "qualification_score": self._calculate_qualification_score(lead_data, platform),
                "missing_criteria": self._get_missing_criteria(session_data, platform),
                "message": "Lead ainda não atingiu critérios de qualificação"
            }
            
        except Exception as e:
            logger.error(f"Erro ao avaliar notificação: {str(e)}")
            return {
                "should_notify": False,
                "reason": "evaluation_error",
                "error": str(e),
                "message": "Erro na avaliação - não notificando por segurança"
            }

    def _calculate_qualification_score(self, lead_data: Dict[str, Any], platform: str) -> float:
        """Calcula score de qualificação do lead (0.0 a 1.0)"""
        try:
            score = 0.0
            
            name = lead_data.get("identification", "").strip()
            if len(name) >= 3:
                score += 0.1
            if len(name.split()) >= 2:
                score += 0.1
                
            contact = lead_data.get("contact_info", "").strip()
            if contact:
                score += 0.1
                if re.search(r'\d{10,11}', contact):
                    score += 0.1
                if re.search(r'\S+@\S+\.\S+', contact):
                    score += 0.1
            
            area = lead_data.get("area_qualification", "").strip()
            if area:
                score += 0.1
                if any(keyword in area.lower() for keyword in ["penal", "saude", "saúde", "criminal", "plano"]):
                    score += 0.1
            
            details = lead_data.get("case_details", "").strip()
            if details:
                score += 0.1
                if len(details) >= 20:
                    score += 0.1
                if len(details) >= 50:
                    score += 0.1
            
            return min(score, 1.0)
            
        except Exception as e:
            logger.error(f"Erro ao calcular score: {str(e)}")
            return 0.0

    def _get_missing_criteria(self, session_data: Dict[str, Any], platform: str) -> list:
        """Identifica critérios faltantes para qualificação"""
        missing = []
        lead_data = session_data.get("lead_data", {})
        
        if not lead_data.get("identification"):
            missing.append("nome_completo")
        if not lead_data.get("contact_info"):
            missing.append("informacoes_contato")
        if not lead_data.get("area_qualification"):
            missing.append("area_juridica")
            
        if platform == "web":
            if not lead_data.get("case_details"):
                missing.append("detalhes_caso")
            if not session_data.get("flow_completed"):
                missing.append("fluxo_incompleto")
        elif platform == "whatsapp":
            if session_data.get("message_count", 0) < 4:
                missing.append("engajamento_insuficiente")
                
        return missing

    async def notify_lawyers_if_qualified(self, session_id: str, session_data: Dict[str, Any], platform: str) -> Dict[str, Any]:
        """Método principal de notificação inteligente"""
        try:
            notification_check = await self.should_notify_lawyers(session_data, platform)
            
            if not notification_check["should_notify"]:
                logger.info(f"📊 Não notificando advogados - Session: {session_id} | Razão: {notification_check['reason']}")
                return {
                    "notified": False,
                    "reason": notification_check["reason"],
                    "details": notification_check
                }
            
            lead_data = session_data.get("lead_data", {})
            user_name = lead_data.get("identification", "Lead Qualificado")
            area = lead_data.get("area_qualification", "não especificada")
            case_details = lead_data.get("case_details", "aguardando mais detalhes")
            contact_info = lead_data.get("contact_info", "")
            
            phone_clean = lead_data.get("phone", "")
            if not phone_clean:
                phone_match = re.search(r'(\d{10,11})', contact_info or "")
                phone_clean = phone_match.group(1) if phone_match else ""
            
            logger.info(f"🚀 NOTIFICANDO ADVOGADOS - Session: {session_id} | Lead: {user_name} | Área: {area} | Platform: {platform}")
            
            try:
                notification_result = await lawyer_notification_service.notify_lawyers_of_new_lead(
                    lead_name=user_name,
                    lead_phone=phone_clean,
                    category=area,
                    additional_info={
                        "case_details": case_details,
                        "contact_info": contact_info,
                        "email": lead_data.get("email", ""),
                        "urgency": "high" if platform == "whatsapp" else "normal",
                        "platform": platform,
                        "qualification_score": notification_check.get("qualification_score", 0),
                        "session_id": session_id,
                        "engagement_level": session_data.get("message_count", 0),
                        "current_step": session_data.get("current_step", ""),
                        "lead_source": f"{platform}_qualified_lead"
                    }
                )
                
                if notification_result.get("success"):
                    session_data["lawyers_notified"] = True
                    session_data["lawyers_notified_at"] = ensure_utc(datetime.now(timezone.utc))
                    await save_user_session(session_id, session_data)
                    
                    logger.info(f"✅ Advogados notificados com sucesso - Session: {session_id}")
                    
                    return {
                        "notified": True,
                        "success": True,
                        "platform": platform,
                        "qualification_score": notification_check.get("qualification_score"),
                        "notification_result": notification_result
                    }
                else:
                    logger.error(f"❌ Falha na notificação dos advogados - Session: {session_id}")
                    return {
                        "notified": True,
                        "success": False,
                        "error": "notification_failed",
                        "details": notification_result
                    }
                    
            except Exception as notification_error:
                logger.error(f"❌ Erro ao notificar advogados - Session: {session_id}: {str(notification_error)}")
                return {
                    "notified": True,
                    "success": False,
                    "error": "notification_exception",
                    "exception": str(notification_error)
                }
                
        except Exception as e:
            logger.error(f"❌ Erro na lógica de notificação - Session: {session_id}: {str(e)}")
            return {
                "notified": False,
                "error": "notification_logic_error",
                "exception": str(e)
            }

    async def get_gemini_health_status(self) -> Dict[str, Any]:
        try:
            test_response = await asyncio.wait_for(
                ai_orchestrator.generate_response("test", session_id="__health_check__"),
                timeout=5.0
            )
            ai_orchestrator.clear_session_memory("__health_check__")
            if test_response and isinstance(test_response, str) and test_response.strip():
                self.gemini_available = True
                return {"service": "gemini_ai", "status": "active", "available": True}
            else:
                self.gemini_available = False
                return {"service": "gemini_ai", "status": "inactive", "available": False}
        except Exception as e:
            self.gemini_available = False
            return {"service": "gemini_ai", "status": "error", "available": False, "error": str(e)}

    async def get_overall_service_status(self) -> Dict[str, Any]:
        try:
            firebase_status = await get_firebase_service_status()
            ai_status = await self.get_gemini_health_status()
            firebase_healthy = firebase_status.get("status") == "active"
            ai_healthy = ai_status.get("status") == "active"
            
            if firebase_healthy and ai_healthy:
                overall_status = "active"
            elif firebase_healthy:
                overall_status = "degraded"
            else:
                overall_status = "error"
                
            return {
                "overall_status": overall_status,
                "firebase_status": firebase_status,
                "ai_status": ai_status,
                "features": {
                    "conversation_flow": firebase_healthy,
                    "ai_responses": ai_healthy,
                    "fallback_mode": firebase_healthy and not ai_healthy,
                    "whatsapp_integration": True,
                    "lead_collection": firebase_healthy,
                    "intelligent_notifications": True
                },
                "gemini_available": self.gemini_available,
                "fallback_mode": not self.gemini_available
            }
        except Exception as e:
            logger.error(f"Error getting overall service status: {str(e)}")
            return {
                "overall_status": "error",
                "error": str(e)
            }

    async def _get_or_create_session(self, session_id: str, platform: str, phone_number: Optional[str] = None) -> Dict[str, Any]:
        """Criar ou obter sessão - inicia direto no fluxo"""
        logger.info(f"Getting/creating session {session_id} for platform {platform}")
        
        session_data = await get_user_session(session_id)
        
        if not session_data:
            session_data = {
                "session_id": session_id,
                "platform": platform,
                "created_at": ensure_utc(datetime.now(timezone.utc)),
                "current_step": "step1_name",
                "lead_data": {},
                "message_count": 0,
                "flow_completed": False,
                "phone_submitted": False,
                "lawyers_notified": False,
                "last_updated": ensure_utc(datetime.now(timezone.utc)),
                "first_interaction": True
            }
            logger.info(f"Created new session {session_id}")
            await save_user_session(session_id, session_data)
            
        if phone_number:
            session_data["phone_number"] = phone_number
            
        return session_data

    def _is_phone_number(self, message: str) -> bool:
        clean_message = ''.join(filter(str.isdigit, (message or "")))
        return 10 <= len(clean_message) <= 13

    def _get_flow_steps(self) -> Dict[str, Dict]:
        """Fluxo humanizado e conversacional"""
        return {
            "step1_name": {
                "question": "Para que eu possa te ajudar da melhor forma, me diga qual é o seu nome completo? 😊",
                "field": "identification",
                "next_step": "step2_contact"
            },
            "step2_contact": {
                "question": "Prazer em conhecê-lo, {user_name}! 🤝\n\nAgora preciso de suas informações de contato para darmos continuidade:\n\n📱 Qual seu melhor WhatsApp?\n📧 E seu e-mail principal?\n\nPode me passar essas duas informações?",
                "field": "contact_info",
                "next_step": "step3_area"
            },
            "step3_area": {
                "question": "Perfeito, {user_name}! 👍\n\nEm qual área do direito você precisa de nossa ajuda?\n\n⚖️ Direito Penal (crimes, investigações, defesas)\n🏥 Direito da Saúde (planos de saúde, ações médicas, liminares)\n\nQual dessas áreas tem a ver com sua situação?",
                "field": "area_qualification",
                "next_step": "step4_details"
            },
            "step4_details": {
                "question": "Entendi, {user_name}. 💼\n\nPara nossos advogados já terem uma visão completa, me conte:\n\n• Sua situação já está na justiça ou é algo que acabou de acontecer?\n• Tem algum prazo urgente ou audiência marcada?\n• Em que cidade isso está ocorrendo?\n\nFique à vontade para me contar os detalhes! 🤝",
                "field": "case_details",
                "next_step": "step5_confirmation"
            },
            "step5_confirmation": {
                "question": "Obrigado por todos esses detalhes, {user_name}! 🙏\n\nSituações como a sua realmente precisam de atenção especializada e rápida.\n\nTenho uma excelente notícia: nossa equipe já resolveu dezenas de casos similares com ótimos resultados! ✅\n\nVou registrar tudo para que o advogado responsável já entenda completamente seu caso e possa te ajudar com agilidade.\n\nEm alguns minutos você estará falando diretamente com um especialista. Podemos prosseguir? 🚀",
                "field": "confirmation",
                "next_step": "completed"
            }
        }

    def _validate_answer(self, answer: str, step: str) -> bool:
        """🔧 VALIDAÇÃO RIGOROSA CORRIGIDA"""
        if not answer or len(answer.strip()) < 2:
            return False
            
        answer_clean = answer.strip()
        
        if step == "step1_name":
            # ✅ VALIDAÇÃO RIGOROSA PARA NOME
            # Deve ter pelo menos 2 palavras
            words = answer_clean.split()
            if len(words) < 2:
                return False
            
            # Cada palavra deve ter pelo menos 2 caracteres
            for word in words:
                if len(word) < 2:
                    return False
                # Não pode ter números
                if any(char.isdigit() for char in word):
                    return False
            
            # Comprimento total entre 4 e 50 caracteres
            if not (4 <= len(answer_clean) <= 50):
                return False
                
            return True
            
        elif step == "step2_contact":
            # Deve ter pelo menos telefone ou email
            has_phone = bool(re.search(r'\d{10,11}', answer_clean))
            has_email = bool(re.search(r'\S+@\S+\.\S+', answer_clean))
            return has_phone or has_email
            
        elif step == "step3_area":
            # ✅ VALIDAÇÃO RIGOROSA PARA ÁREA JURÍDICA
            area_keywords = [
                'penal', 'criminal', 'crime', 'preso', 'prisão', 'delegacia', 'inquérito',
                'saude', 'saúde', 'plano', 'médico', 'hospital', 'cirurgia', 'tratamento', 
                'liminar', 'ans', 'convênio', 'unimed', 'bradesco', 'amil'
            ]
            return any(keyword in answer_clean.lower() for keyword in area_keywords)
            
        elif step == "step4_details":
            # Detalhes substanciais
            return len(answer_clean) >= 15
            
        elif step == "step5_confirmation":
            # Confirmação simples
            confirmation_words = ['sim', 'ok', 'pode', 'vamos', 'claro', 'certo', 'confirmo']
            return any(word in answer_clean.lower() for word in confirmation_words)
            
        return True

    def _extract_contact_info(self, contact_text: str) -> tuple:
        phone_match = re.search(r'(\d{10,11})', contact_text or "")
        email_match = re.search(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', contact_text or "")
        phone = phone_match.group(1) if phone_match else ""
        email = email_match.group(1) if email_match else ""
        return phone, email

    async def _process_conversation_flow(self, session_data: Dict[str, Any], message: str) -> str:
        """Processar fluxo conversacional humanizado com notificação inteligente"""
        try:
            session_id = session_data["session_id"]
            current_step = session_data.get("current_step", "step1_name")
            lead_data = session_data.get("lead_data", {})
            is_first_interaction = session_data.get("first_interaction", False)
            platform = session_data.get("platform", "web")
            
            logger.info(f"Processing conversation - Step: {current_step}, Message: '{message[:50]}...', Platform: {platform}")
            
            flow_steps = self._get_flow_steps()

            # Se é primeira interação, mostra saudação + primeira pergunta
            if is_first_interaction:
                session_data["first_interaction"] = False
                await save_user_session(session_id, session_data)
                greeting = self._get_personalized_greeting()
                return greeting

            # Fluxo já completado
            if current_step == "completed":
                user_name = lead_data.get("identification", "").split()[0] if lead_data.get("identification") else ""
                return f"Obrigado, {user_name}! Nossa equipe já foi notificada e entrará em contato em breve. 😊"

            # Processar steps do fluxo
            if current_step in flow_steps:
                step_config = flow_steps[current_step]
                
                # ✅ VALIDAÇÃO RIGOROSA
                if not self._validate_answer(message, current_step):
                    user_name = lead_data.get("identification", "").split()[0] if lead_data.get("identification") else ""
                    
                    # ✅ MENSAGENS DE ERRO ESPECÍFICAS
                    retry_messages = {
                        "step1_name": "Por favor, me diga seu nome completo (nome e sobrenome, sem números). Exemplo: João Silva 😊",
                        "step2_contact": f"Preciso de suas informações de contato, {user_name}. Me passe seu WhatsApp (com DDD) e/ou e-mail.",
                        "step3_area": f"{user_name}, preciso saber se é Direito Penal (crimes, investigações) ou Direito da Saúde (planos de saúde, liminares médicas).",
                        "step4_details": f"Me conte mais detalhes sobre sua situação, {user_name}. Quanto mais informações, melhor poderemos te ajudar!",
                        "step5_confirmation": f"Posso prosseguir com o registro das suas informações, {user_name}? (Responda: sim, ok, pode prosseguir)"
                    }
                    return retry_messages.get(current_step, "Por favor, me dê mais detalhes para que eu possa te ajudar melhor.")
                
                # Salvar resposta
                field_name = step_config["field"]
                lead_data[field_name] = message.strip()
                
                # Extrair informações de contato se for step2
                if current_step == "step2_contact":
                    phone, email = self._extract_contact_info(message)
                    if phone:
                        lead_data["phone"] = phone
                    if email:
                        lead_data["email"] = email
                
                session_data["lead_data"] = lead_data
                
                # Verificar se deve notificar advogados (antes de avançar)
                notification_result = await self.notify_lawyers_if_qualified(session_id, session_data, platform)
                if notification_result.get("notified") and notification_result.get("success"):
                    logger.info(f"✅ Advogados notificados durante fluxo - Step: {current_step}, Session: {session_id}")
                
                # Avançar para próximo step
                next_step = step_config["next_step"]
                
                if next_step == "completed":
                    session_data["current_step"] = "completed"
                    session_data["flow_completed"] = True
                    await save_user_session(session_id, session_data)
                    return await self._handle_lead_finalization(session_id, session_data)
                else:
                    session_data["current_step"] = next_step
                    await save_user_session(session_id, session_data)
                    
                    next_step_config = flow_steps[next_step]
                    return self._interpolate_message(next_step_config["question"], lead_data)

            # Estado inválido - reiniciar
            logger.warning(f"Invalid state: {current_step}, resetting")
            session_data["current_step"] = "step1_name"
            session_data["first_interaction"] = True
            await save_user_session(session_id, session_data)
            return self._get_personalized_greeting()

        except Exception as e:
            logger.error(f"Exception in conversation flow: {str(e)}")
            return self._get_personalized_greeting()

    def _interpolate_message(self, message: str, lead_data: Dict[str, Any]) -> str:
        """Interpolar dados do usuário na mensagem"""
        try:
            if not message:
                return "Como posso ajudá-lo?"
                
            user_name = lead_data.get("identification", "")
            if user_name and "{user_name}" in message:
                first_name = user_name.split()[0]
                message = message.replace("{user_name}", first_name)
                
            area = lead_data.get("area_qualification", "")
            if area and "{area}" in message:
                message = message.replace("{area}", area)
                
            return message
        except Exception as e:
            logger.error(f"Error interpolating message: {str(e)}")
            return message

    async def _handle_lead_finalization(self, session_id: str, session_data: Dict[str, Any]) -> str:
        """
        🎯 FINALIZAÇÃO CORRIGIDA - SEPARADA POR PLATAFORMA
        
        Chat da Landing: Finalização simples sem WhatsApp
        Botão WhatsApp: Mensagem estratégica via WhatsApp
        """
        try:
            logger.info(f"Lead finalization for session: {session_id}")
            
            lead_data = session_data.get("lead_data", {})
            platform = session_data.get("platform", "web")
            user_name = lead_data.get("identification", "Cliente")
            first_name = user_name.split()[0] if user_name else "Cliente"
            
            # ✅ CHAT DA LANDING - FINALIZAÇÃO SIMPLES SEM WHATSAPP
            if platform == "web":
                # Notificar advogados se ainda não foram notificados
                notification_result = await self.notify_lawyers_if_qualified(session_id, session_data, platform)
                
                # Salvar lead data
                try:
                    answers = []
                    field_mapping = {
                        "identification": {"id": 1, "answer": lead_data.get("identification", "")},
                        "contact_info": {"id": 2, "answer": lead_data.get("contact_info", "")},
                        "area_qualification": {"id": 3, "answer": lead_data.get("area_qualification", "")},
                        "case_details": {"id": 4, "answer": lead_data.get("case_details", "")},
                        "confirmation": {"id": 5, "answer": lead_data.get("confirmation", "")}
                    }
                    
                    for field, data in field_mapping.items():
                        if data["answer"]:
                            answers.append(data)

                    lead_id = await save_lead_data({"answers": answers})
                    logger.info(f"💾 Lead salvo com ID: {lead_id}")
                        
                except Exception as save_error:
                    logger.error(f"❌ Erro ao salvar lead: {str(save_error)}")

                # ✅ TESTE DE ENVIO WHATSAPP PARA CHAT DA LANDING
                phone_clean = lead_data.get("phone", "")
                if not phone_clean:
                    contact_info = lead_data.get("contact_info", "")
                    phone_match = re.search(r'(\d{10,11})', contact_info or "")
                    phone_clean = phone_match.group(1) if phone_match else ""
                
                if phone_clean and len(phone_clean) >= 10:
                    logger.info(f"📱 Testando envio WhatsApp para lead do chat da landing")
                    test_message = f"Olá {first_name}! Recebemos suas informações através do nosso site. Nossa equipe entrará em contato em breve para dar prosseguimento ao seu caso jurídico. Obrigado por confiar no m.lima Advogados!"
                    
                    try:
                        # ✅ CORREÇÃO: Passar apenas phone_clean (sem @s.whatsapp.net)
                        whatsapp_success = await baileys_service.send_whatsapp_message(phone_clean, test_message)
                        if whatsapp_success:
                            logger.info(f"✅ Mensagem de teste enviada com sucesso para {phone_clean}")
                        else:
                            logger.error(f"❌ Falha no envio da mensagem de teste para {phone_clean}")
                    except Exception as whatsapp_error:
                        logger.error(f"❌ Erro ao enviar mensagem de teste: {str(whatsapp_error)}")

                # ✅ MENSAGEM FINAL SIMPLES - SEM WHATSAPP
                notification_status = ""
                if notification_result.get("notified") and notification_result.get("success"):
                    notification_status = " ⚡ Nossa equipe foi imediatamente notificada!"
                
                final_message = f"""Perfeito, {first_name}! ✅

Todas suas informações foram registradas com sucesso{notification_status}

Um advogado experiente do m.lima entrará em contato com você em breve para dar prosseguimento ao seu caso com toda atenção necessária.

Você fez a escolha certa ao confiar no escritório m.lima! 🤝

Nossa equipe entrará em contato em alguns minutos."""

                return final_message
            
            # ✅ WHATSAPP - FINALIZAÇÃO COM MENSAGEM ESTRATÉGICA
            else:
                # Extrair telefone
                phone_clean = lead_data.get("phone", "")
                if not phone_clean:
                    contact_info = lead_data.get("contact_info", "")
                    phone_match = re.search(r'(\d{10,11})', contact_info or "")
                    phone_clean = phone_match.group(1) if phone_match else ""
                    
                if not phone_clean or len(phone_clean) < 10:
                    return f"Para finalizar, {first_name}, preciso do seu WhatsApp com DDD (ex: 11999999999):"

                # Formatar telefone
                phone_formatted = self._format_brazilian_phone(phone_clean)
                
                # Atualizar dados da sessão
                session_data.update({
                    "phone_number": phone_clean,
                    "phone_formatted": phone_formatted,
                    "phone_submitted": True,
                    "lead_qualified": True,
                    "last_updated": ensure_utc(datetime.now(timezone.utc))
                })
                
                await save_user_session(session_id, session_data)

                # Notificar advogados se ainda não foram notificados
                notification_result = await self.notify_lawyers_if_qualified(session_id, session_data, platform)
                
                # Salvar lead data
                try:
                    answers = []
                    field_mapping = {
                        "identification": {"id": 1, "answer": lead_data.get("identification", "")},
                        "contact_info": {"id": 2, "answer": lead_data.get("contact_info", "")},
                        "area_qualification": {"id": 3, "answer": lead_data.get("area_qualification", "")},
                        "case_details": {"id": 4, "answer": lead_data.get("case_details", "")},
                        "confirmation": {"id": 5, "answer": lead_data.get("confirmation", "")}
                    }
                    
                    for field, data in field_mapping.items():
                        if data["answer"]:
                            answers.append(data)
                    
                    if phone_clean:
                        answers.append({"id": 99, "field": "phone_extracted", "answer": phone_clean})

                    lead_id = await save_lead_data({"answers": answers})
                    logger.info(f"💾 Lead salvo com ID: {lead_id}")
                        
                except Exception as save_error:
                    logger.error(f"❌ Erro ao salvar lead: {str(save_error)}")

                # 📱 ENVIAR WHATSAPP ESTRATÉGICO
                area = lead_data.get("area_qualification", "direito")
                
                # ✅ MENSAGEM DIFERENTE POR PLATAFORMA
                if platform == "web":
                    # Chat da Landing - mensagem simples
                    whatsapp_message = f"""Olá {first_name}! 👋

Suas informações foram registradas no m.lima Advogados.

Nossa equipe especializada em {area} entrará em contato com você em breve para dar prosseguimento ao seu caso.

Obrigado pela confiança! 🤝"""
                else:
                    # WhatsApp - mensagem estratégica completa
                    whatsapp_message = self._get_strategic_whatsapp_message(user_name, area, phone_formatted)
                
                whatsapp_success = False
                
                try:
                    # ✅ CORREÇÃO: Passar apenas número limpo (sem @s.whatsapp.net)
                    whatsapp_success = await baileys_service.send_whatsapp_message(phone_formatted, whatsapp_message)
                    
                    if whatsapp_success:
                        logger.info(f"✅ WhatsApp enviado com sucesso para {phone_formatted}")
                    else:
                        logger.error(f"❌ Falha no envio WhatsApp para {phone_formatted}")
                        
                except Exception as whatsapp_error:
                    logger.error(f"❌ EXCEÇÃO ao enviar WhatsApp: {str(whatsapp_error)}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")

                # 🎯 MENSAGEM FINAL PERSONALIZADA
                notification_status = ""
                if notification_result.get("notified") and notification_result.get("success"):
                    notification_status = " ⚡ Nossa equipe foi imediatamente notificada!"
                
                final_message = f"""Perfeito, {first_name}! ✅

Todas suas informações foram registradas com sucesso{notification_status}

{'🎯 CHAT DA LANDING: ' if platform == 'web' else ''}Um advogado experiente do m.lima entrará em contato com você em breve para dar prosseguimento ao seu caso com toda atenção necessária.

{'📱 Mensagem de confirmação enviada no seu WhatsApp!' if whatsapp_success else '📝 Suas informações foram salvas com segurança.'}

Você fez a escolha certa ao confiar no escritório m.lima para cuidar do seu caso! 🤝

Em alguns minutos, um especialista entrará em contato."""

                return final_message
            
        except Exception as e:
            logger.error(f"❌ Erro na finalização do lead: {str(e)}")
            user_name = session_data.get("lead_data", {}).get("identification", "")
            first_name = user_name.split()[0] if user_name else ""
            return f"Obrigado pelas informações, {first_name}! Nossa equipe entrará em contato em breve. 😊"

    async def _handle_phone_collection(self, phone_message: str, session_id: str, session_data: Dict[str, Any]) -> str:
        """Coleta de telefone com toque humano"""
        try:
            phone_clean = ''.join(filter(str.isdigit, phone_message))
            user_name = session_data.get("lead_data", {}).get("identification", "")
            first_name = user_name.split()[0] if user_name else ""
            
            if len(phone_clean) < 10 or len(phone_clean) > 13:
                return f"Ops, {first_name}! Número inválido. Digite seu WhatsApp com DDD (ex: 11999999999):"

            session_data["lead_data"]["phone"] = phone_clean
            return await self._handle_lead_finalization(session_id, session_data)
            
        except Exception as e:
            logger.error(f"Error in phone collection: {str(e)}")
            user_name = session_data.get("lead_data", {}).get("identification", "")
            first_name = user_name.split()[0] if user_name else ""
            return f"Obrigado, {first_name}! Nossa equipe entrará em contato em breve. 😊"

    async def process_message(self, message: str, session_id: str, phone_number: Optional[str] = None, platform: str = "web") -> Dict[str, Any]:
        """Processamento principal com notificação inteligente"""
        try:
            logger.info(f"Processing message - Session: {session_id}, Platform: {platform}")
            logger.info(f"Message: '{message}'")

            session_data = await self._get_or_create_session(session_id, platform, phone_number)
            
            # Tratar coleta de telefone para leads qualificados
            if (session_data.get("lead_qualified", False) and 
                not session_data.get("phone_submitted", False) and 
                self._is_phone_number(message)):
                
                phone_response = await self._handle_phone_collection(message, session_id, session_data)
                return {
                    "response_type": "phone_collected",
                    "platform": platform,
                    "session_id": session_id,
                    "response": phone_response,
                    "phone_submitted": True,
                    "message_count": session_data.get("message_count", 0) + 1
                }

            # Processar fluxo principal
            response = await self._process_conversation_flow(session_data, message)
            
            # Atualizar contadores
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            session_data["last_updated"] = ensure_utc(datetime.now(timezone.utc))
            await save_user_session(session_id, session_data)
            
            result = {
                "response_type": f"{platform}_flow",
                "platform": platform,
                "session_id": session_id,
                "response": response,
                "ai_mode": False,
                "current_step": session_data.get("current_step"),
                "flow_completed": session_data.get("flow_completed", False),
                "lawyers_notified": session_data.get("lawyers_notified", False),
                "lead_data": session_data.get("lead_data", {}),
                "message_count": session_data.get("message_count", 1),
                "qualification_score": self._calculate_qualification_score(
                    session_data.get("lead_data", {}), platform
                )
            }
            
            # Garantir que response sempre existe e é string
            if not result.get("response") or not isinstance(result["response"], str):
                result["response"] = "Como posso ajudá-lo hoje?"
                logger.warning(f"⚠️ Response vazio corrigido para session {session_id}")
            
            return result

        except Exception as e:
            logger.error(f"Exception in process_message: {str(e)}")
            return {
                "response_type": "orchestration_error",
                "platform": platform,
                "session_id": session_id,
                "response": self._get_personalized_greeting() or "Olá! Como posso ajudá-lo?",
                "error": str(e)
            }

    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]):
        """Handler para autorização WhatsApp"""
        try:
            session_id = auth_data.get("session_id", "")
            phone_number = auth_data.get("phone_number", "")
            source = auth_data.get("source", "unknown")
            user_data = auth_data.get("user_data", {})
            
            logger.info(f"🎯 Processando autorização WhatsApp - Session: {session_id}, Phone: {phone_number}, Source: {source}")
            
            # Se tem dados do usuário (ex: do chat da landing), criar sessão pré-populada
            if user_data and source == "landing_chat":
                session_data = {
                    "session_id": session_id,
                    "platform": "whatsapp",
                    "phone_number": phone_number,
                    "created_at": ensure_utc(datetime.now(timezone.utc)),
                    "current_step": "completed",
                    "lead_data": {
                        "identification": user_data.get("name", ""),
                        "contact_info": f"{phone_number} {user_data.get('email', '')}".strip(),
                        "area_qualification": "não especificada",
                        "case_details": user_data.get("problem", "Detalhes do chat da landing"),
                        "phone": phone_number,
                        "email": user_data.get("email", "")
                    },
                    "message_count": 1,
                    "flow_completed": True,
                    "phone_submitted": True,
                    "lead_qualified": True,
                    "lawyers_notified": False,
                    "last_updated": ensure_utc(datetime.now(timezone.utc)),
                    "first_interaction": False,
                    "authorization_source": source
                }
                
                await save_user_session(session_id, session_data)
                
                # Notificar advogados imediatamente para leads da landing
                notification_result = await self.notify_lawyers_if_qualified(session_id, session_data, "whatsapp")
                
                logger.info(f"✅ Sessão pré-populada criada para lead da landing - Session: {session_id}")
                
            else:
                # Autorização de botão - criar sessão vazia para futuras mensagens
                logger.info(f"📝 Autorização de botão registrada - Session: {session_id} - Aguardando primeira mensagem")
            
            return {
                "status": "authorization_processed",
                "session_id": session_id,
                "phone_number": phone_number,
                "source": source,
                "pre_populated": bool(user_data and source == "landing_chat")
            }
            
        except Exception as e:
            logger.error(f"❌ Erro no processamento da autorização WhatsApp: {str(e)}")
            return {
                "status": "authorization_error",
                "error": str(e)
            }

    async def handle_phone_number_submission(self, phone_number: str, session_id: str) -> Dict[str, Any]:
        """Handle phone number submission from web interface."""
        try:
            logger.info(f"Phone number submission for session {session_id}: {phone_number}")
            session_data = await get_user_session(session_id) or {}
            response = await self._handle_phone_collection(phone_number, session_id, session_data)
            return {
                "status": "success",
                "message": response,
                "phone_submitted": True
            }
        except Exception as e:
            logger.error(f"Error in phone submission: {str(e)}")
            return {
                "status": "error",
                "message": "Erro ao processar número de WhatsApp",
                "error": str(e)
            }

    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """Get current session context and status."""
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return {"exists": False}

            context = {
                "exists": True,
                "session_id": session_id,
                "platform": session_data.get("platform", "unknown"),
                "current_step": session_data.get("current_step"),
                "flow_completed": session_data.get("flow_completed", False),
                "phone_submitted": session_data.get("phone_submitted", False),
                "lawyers_notified": session_data.get("lawyers_notified", False),
                "lead_data": session_data.get("lead_data", {}),
                "message_count": session_data.get("message_count", 0),
                "qualification_score": self._calculate_qualification_score(
                    session_data.get("lead_data", {}), 
                    session_data.get("platform", "web")
                )
            }
            
            return context
        except Exception as e:
            logger.error(f"Error getting session context: {str(e)}")
            return {"exists": False, "error": str(e)}


# Global instance
intelligent_orchestrator = IntelligentHybridOrchestrator()
hybrid_orchestrator = intelligent_orchestrator