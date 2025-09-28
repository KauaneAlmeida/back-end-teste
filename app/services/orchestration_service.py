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
        """
        🎯 MENSAGEM INICIAL ESTRATÉGICA OTIMIZADA
        
        Elementos psicológicos para conversão:
        ✅ Autoridade (escritório especializado, resultados)
        ✅ Urgência suave (situações que não podem esperar)
        ✅ Personalização (horário do dia)
        ✅ Prova social (milhares de casos)
        ✅ Benefício claro (solução rápida e eficaz)
        ✅ Call-to-action natural
        """
        now = datetime.now()
        hour = now.hour
        
        if 5 <= hour < 12:
            greeting = "Bom dia"
        elif 12 <= hour < 18:
            greeting = "Boa tarde"
        else:
            greeting = "Boa noite"
        
        # 🎯 MENSAGEM ESTRATÉGICA ÚNICA que funciona para ambas as plataformas
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
        """
        🎯 MENSAGEM ESTRATÉGICA OTIMIZADA PARA CONVERSÃO
        
        Elementos psicológicos incluídos:
        ✅ Urgência (minutos, tempo limitado)
        ✅ Autoridade (equipe especializada, experiente) 
        ✅ Prova social (dezenas de casos resolvidos)
        ✅ Exclusividade (atenção personalizada)
        ✅ Benefício claro (resultados, agilidade)
        """
        first_name = user_name.split()[0] if user_name else "Cliente"
        
        # Personalizar por área jurídica
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
        
        # Detectar área
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
        """
        🧠 LÓGICA INTELIGENTE DE NOTIFICAÇÃO
        
        Decide quando notificar advogados baseado na plataforma e qualificação do lead
        Evita notificações prematuras e spam para a equipe jurídica
        """
        try:
            # Verificar se já foram notificados
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
            
            # CRITÉRIOS POR PLATAFORMA
            if platform == "web":
                # Web Chat - critérios mais rigorosos (usuário já completou fluxo na página)
                required_fields = ["identification", "contact_info", "area_qualification", "case_details"]
                has_required_fields = all(lead_data.get(field) for field in required_fields)
                
                criteria_met = (
                    flow_completed and 
                    has_required_fields and
                    len(lead_data.get("identification", "").strip()) >= 3 and  # Nome mínimo
                    len(lead_data.get("case_details", "").strip()) >= 15  # Detalhes mínimos
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
                # WhatsApp - critérios adaptados para conversação mais natural
                required_fields = ["identification", "contact_info", "area_qualification"]
                has_required_fields = all(lead_data.get(field) for field in required_fields)
                
                # Critérios para WhatsApp
                engagement_criteria = (
                    message_count >= 4 and  # Pelo menos 4 interações
                    has_required_fields and
                    len(lead_data.get("identification", "").strip()) >= 3 and  # Nome válido
                    len(lead_data.get("area_qualification", "").strip()) >= 3  # Área identificada
                )
                
                # Verificar se chegou no step de detalhes ou confirmação
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
            
            # Não qualificado ainda
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
            
            # Nome completo (0.2)
            name = lead_data.get("identification", "").strip()
            if len(name) >= 3:
                score += 0.1
            if len(name.split()) >= 2:  # Nome e sobrenome
                score += 0.1
                
            # Informações de contato (0.3)
            contact = lead_data.get("contact_info", "").strip()
            if contact:
                score += 0.1
                # Verificar se tem telefone
                if re.search(r'\d{10,11}', contact):
                    score += 0.1
                # Verificar se tem email
                if re.search(r'\S+@\S+\.\S+', contact):
                    score += 0.1
            
            # Área jurídica identificada (0.2)
            area = lead_data.get("area_qualification", "").strip()
            if area:
                score += 0.1
                # Áreas específicas que atendemos
                if any(keyword in area.lower() for keyword in ["penal", "saude", "saúde", "criminal", "plano"]):
                    score += 0.1
            
            # Detalhes do caso (0.3)
            details = lead_data.get("case_details", "").strip()
            if details:
                score += 0.1
                if len(details) >= 20:  # Detalhes substanciais
                    score += 0.1
                if len(details) >= 50:  # Detalhes completos
                    score += 0.1
            
            return min(score, 1.0)  # Máximo 1.0
            
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
        """
        🎯 MÉTODO PRINCIPAL DE NOTIFICAÇÃO INTELIGENTE
        
        Avalia se deve notificar e executa a notificação se qualificado
        """
        try:
            # Avaliar se deve notificar
            notification_check = await self.should_notify_lawyers(session_data, platform)
            
            if not notification_check["should_notify"]:
                logger.info(f"📊 Não notificando advogados - Session: {session_id} | Razão: {notification_check['reason']}")
                return {
                    "notified": False,
                    "reason": notification_check["reason"],
                    "details": notification_check
                }
            
            # 🚀 LEAD QUALIFICADO - NOTIFICAR ADVOGADOS
            lead_data = session_data.get("lead_data", {})
            user_name = lead_data.get("identification", "Lead Qualificado")
            area = lead_data.get("area_qualification", "não especificada")
            case_details = lead_data.get("case_details", "aguardando mais detalhes")
            contact_info = lead_data.get("contact_info", "")
            
            # Extrair telefone
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
                    # Marcar como notificado
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
                "current_step": "step1_name",  # Começa direto perguntando o nome
                "lead_data": {},
                "message_count": 0,
                "flow_completed": False,
                "phone_submitted": False,
                "lawyers_notified": False,  # 🎯 NOVO: Flag para controlar notificações
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
        """Validação flexível e humanizada"""
        if not answer or len(answer.strip()) < 2:
            return False
            
        if step == "step1_name":
            return len(answer.split()) >= 1  # Pelo menos um nome
        elif step == "step2_contact":
            return len(answer.strip()) >= 8  # Telefone ou email básico
        elif step == "step3_area":
            keywords = ['penal', 'saude', 'saúde', 'criminal', 'liminar', 'medic', 'plano']
            return any(keyword in answer.lower() for keyword in keywords)
        elif step == "step4_details":
            return len(answer.strip()) >= 15  # Detalhes mínimos
            
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
                
                # Validar resposta
                if not self._validate_answer(message, current_step):
                    user_name = lead_data.get("identification", "").split()[0] if lead_data.get("identification") else ""
                    retry_messages = {
                        "step1_name": "Por favor, me diga seu nome completo para continuarmos. 😊",
                        "step2_contact": f"Preciso de suas informações de contato, {user_name}. Pode me passar seu WhatsApp e e-mail?",
                        "step3_area": f"{user_name}, qual área do direito você precisa? Penal ou Saúde?",
                        "step4_details": f"Me conte mais detalhes sobre sua situação, {user_name}. Quanto mais informações, melhor poderemos te ajudar!"
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
                
                # 🎯 VERIFICAR SE DEVE NOTIFICAR ADVOGADOS (antes de avançar)
                notification_result = await self.notify_lawyers_if_qualified(session_id, session_data, platform)
                if notification_result.get("notified") and notification_result.get("success"):
                    logger.info(f"✅ Advogados notificados durante fluxo - Step: {current_step}, Session: {session_id}")
                
                # Avançar para próximo step
                next_step = step_config["next_step"]
                
                if next_step == "completed":
                    # Finalizar fluxo
                    session_data["current_step"] = "completed"
                    session_data["flow_completed"] = True
                    await save_user_session(session_id, session_data)
                    return await self._handle_lead_finalization(session_id, session_data)
                else:
                    # Próxima pergunta
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
                # Usar apenas o primeiro nome
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
        """🎯 FINALIZAÇÃO INTELIGENTE COM MENSAGEM ESTRATÉGICA"""
        try:
            logger.info(f"Lead finalization for session: {session_id}")
            
            lead_data = session_data.get("lead_data", {})
            platform = session_data.get("platform", "web")
            user_name = lead_data.get("identification", "Cliente")
            first_name = user_name.split()[0] if user_name else "Cliente"
            
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

            # 🚀 NOTIFICAR ADVOGADOS SE AINDA NÃO FORAM NOTIFICADOS
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
                logger.info(f"Lead saved with ID: {lead_id}")
                    
            except Exception as save_error:
                logger.error(f"Error saving lead: {str(save_error)}")

            # 📱 ENVIAR WHATSAPP ESTRATÉGICO
            area = lead_data.get("area_qualification", "direito")
            strategic_message = self._get_strategic_whatsapp_message(user_name, area, phone_formatted)
            
            whatsapp_number = f"{phone_formatted}@s.whatsapp.net"
            whatsapp_success = False
            
            try:
                await baileys_service.send_whatsapp_message(whatsapp_number, strategic_message)
                logger.info(f"📱 WhatsApp estratégico enviado com sucesso para {phone_formatted}")
                whatsapp_success = True
            except Exception as whatsapp_error:
                logger.error(f"❌ Erro ao enviar WhatsApp estratégico: {str(whatsapp_error)}")

            # 🎯 MENSAGEM FINAL PERSONALIZADA
            notification_status = ""
            if notification_result.get("notified") and notification_result.get("success"):
                notification_status = " ⚡ Nossa equipe foi imediatamente notificada!"
            
            final_message = f"""Perfeito, {first_name}! ✅

Todas suas informações foram registradas com sucesso{notification_status}

Um advogado experiente do m.lima entrará em contato com você em breve para dar prosseguimento ao seu caso com toda atenção necessária.

{'📱 Mensagem de confirmação enviada no seu WhatsApp!' if whatsapp_success else '📝 Suas informações foram salvas com segurança.'}

Você fez a escolha certa ao confiar no escritório m.lima para cuidar do seu caso! 🤝

Em alguns minutos, um especialista entrará em contato."""

            return final_message
            
        except Exception as e:
            logger.error(f"Error in lead finalization: {str(e)}")
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
        """🎯 PROCESSAMENTO PRINCIPAL COM NOTIFICAÇÃO INTELIGENTE"""
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
            
            # ✅ GARANTIR QUE RESPONSE SEMPRE EXISTE E É STRING
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
        """
        Handler for WhatsApp authorization from landing page.
        
        Called when user completes landing page form - triggers initial WhatsApp message.
        """
        try:
            session_id = auth_data.get("session_id", "")
            phone_number = auth_data.get("phone_number", "")
            source = auth_data.get("source", "unknown")
            user_data = auth_data.get("user_data", {})
            
            logger.info(f"Processing WhatsApp authorization - Session: {session_id}, Phone: {phone_number}")
            
            # Create WhatsApp session for future messages
            session_data = {
                "session_id": session_id,
                "platform": "whatsapp", 
                "phone_number": phone_number,
                "created_at": ensure_utc(datetime.now(timezone.utc)),
                "current_step": "step1_name",
                "lead_data": {},
                "message_count": 0,
                "flow_completed": False,
                "phone_submitted": False,
                "lawyers_notified": False,
                "last_updated": ensure_utc(datetime.now(timezone.utc)),
                "first_interaction": True,
                "authorization_source": source
            }
            
            await save_user_session(session_id, session_data)
            
            # Send initial strategic WhatsApp message
            user_name = user_data.get("name", "Cliente")
            initial_message = self._get_strategic_initial_message(user_name, session_id)
            
            # Format phone for WhatsApp
            phone_formatted = self._format_brazilian_phone(phone_number)
            whatsapp_number = f"{phone_formatted}@s.whatsapp.net"
            
            # Send via Baileys service
            message_sent = await baileys_service.send_whatsapp_message(whatsapp_number, initial_message)
            
            if message_sent:
                logger.info(f"Initial WhatsApp message sent successfully to {phone_number}")
            else:
                logger.error(f"Failed to send initial WhatsApp message to {phone_number}")
            
            return {
                "status": "authorization_processed",
                "session_id": session_id,
                "phone_number": phone_number,
                "source": source,
                "message_sent": message_sent
            }
            
        except Exception as e:
            logger.error(f"Error processing WhatsApp authorization: {str(e)}")
            return {
                "status": "authorization_error",
                "error": str(e)
            }
    
    def _get_strategic_initial_message(self, user_name: str, session_id: str) -> str:
        """Generate strategic initial WhatsApp message with session_id."""
        first_name = user_name.split()[0] if user_name else "Cliente"
        
        return f"""Olá {first_name}! 👋

Obrigado por entrar em contato com o escritório m.lima através do nosso site.

Recebemos suas informações e nossa equipe especializada está pronta para te ajudar com seu caso jurídico.

Para darmos continuidade ao seu atendimento de forma personalizada, responda esta mensagem com mais detalhes sobre sua situação.

🆔 Sessão: {session_id}

---
✉️ m.lima Advogados Associados
📱 Atendimento prioritário ativado"""

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