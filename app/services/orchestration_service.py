"""
Production-Ready Orchestration Service

Refatoração completa para resolver problemas críticos:
- Fluxo conversacional flexível com extração inteligente de dados
- Race conditions resolvidas com locks por sessão
- Error recovery que preserva estado do usuário
- Memory management com TTL automático
- Validações robustas com regex patterns
- Retry logic para notificações críticas
- Rate limiting e proteção contra spam
- Logs estruturados com correlation IDs
"""

import logging
import json
import os
import re
import asyncio
import uuid
from typing import Dict, Any, Optional, Set, Tuple, List
from datetime import datetime, timezone, timedelta
from enum import Enum
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager

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

# =================== CONFIGURATION ===================

class Config:
    """Centralized configuration with environment variable support"""
    SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
    MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
    RATE_LIMIT_MESSAGES_PER_MINUTE = int(os.getenv("RATE_LIMIT_MESSAGES_PER_MINUTE", "10"))
    OPERATION_TIMEOUT_SECONDS = int(os.getenv("OPERATION_TIMEOUT_SECONDS", "5"))
    NOTIFICATION_RETRY_ATTEMPTS = int(os.getenv("NOTIFICATION_RETRY_ATTEMPTS", "3"))
    LOCK_TIMEOUT_SECONDS = int(os.getenv("LOCK_TIMEOUT_SECONDS", "30"))
    LAW_FIRM_NUMBER = os.getenv("LAW_FIRM_NUMBER", "+5511918368812")

# =================== ENUMS AND DATA CLASSES ===================

class FlowState(Enum):
    """Well-defined flow states"""
    INITIAL = "initial"
    COLLECTING_DATA = "collecting_data"
    VALIDATING_DATA = "validating_data"
    COMPLETED = "completed"
    ERROR_RECOVERY = "error_recovery"

@dataclass
class ExtractedData:
    """Structured data extracted from user messages"""
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    legal_area: Optional[str] = None
    urgency_level: str = "normal"
    case_description: Optional[str] = None
    confidence_score: float = 0.0

@dataclass
class SessionContext:
    """Complete session context with metadata"""
    session_id: str
    platform: str
    state: FlowState
    extracted_data: ExtractedData
    message_count: int = 0
    created_at: datetime = None
    last_updated: datetime = None
    error_count: int = 0
    rate_limit_count: int = 0
    correlation_id: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.last_updated is None:
            self.last_updated = datetime.now(timezone.utc)
        if self.correlation_id is None:
            self.correlation_id = str(uuid.uuid4())[:8]

# =================== REGEX PATTERNS ===================

class DataPatterns:
    """Robust regex patterns for data extraction"""
    
    # Brazilian phone patterns (various formats)
    PHONE_PATTERNS = [
        r'\b(?:\+?55\s?)?(?:\(?(?:11|12|13|14|15|16|17|18|19|21|22|24|27|28|31|32|33|34|35|37|38|41|42|43|44|45|46|47|48|49|51|53|54|55|61|62|63|64|65|66|67|68|69|71|73|74|75|77|79|81|82|83|84|85|86|87|88|89|91|92|93|94|95|96|97|98|99)\)?\s?)?(?:9\s?)?(?:\d{4}[\s\-]?\d{4})\b',
        r'\b(?:\+?55\s?)?(?:\d{2}\s?)?9?\d{8,9}\b'
    ]
    
    # Email pattern
    EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    
    # Name patterns (including compound names with accents)
    NAME_PATTERNS = [
        r'\b(?:meu nome é|me chamo|sou o|sou a|eu sou)\s+([A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇ][a-záéíóúàèìòùâêîôûãõç]+(?:\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇ][a-záéíóúàèìòùâêîôûãõç]+)*)\b',
        r'^([A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇ][a-záéíóúàèìòùâêîôûãõç]+(?:\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇ][a-záéíóúàèìòùâêîôûãõç]+)+)$'
    ]
    
    # Legal area keywords
    LEGAL_AREAS = {
        'penal': ['penal', 'criminal', 'crime', 'preso', 'prisão', 'delegacia', 'inquérito', 'processo criminal', 'advogado criminal'],
        'saude': ['saúde', 'saude', 'plano', 'médico', 'hospital', 'cirurgia', 'tratamento', 'liminar', 'ans', 'convênio']
    }
    
    # Urgency indicators
    URGENCY_KEYWORDS = [
        'urgente', 'emergência', 'emergencia', 'rápido', 'rapido', 'hoje', 'agora',
        'preso', 'audiência', 'audiencia', 'prazo', 'vence', 'amanhã', 'amanha'
    ]

# =================== SESSION MANAGER ===================

class SessionManager:
    """Manages session locks and atomic operations"""
    
    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._rate_limits: Dict[str, List[datetime]] = {}
    
    @asynccontextmanager
    async def session_lock(self, session_id: str):
        """Async context manager for session locks"""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        
        lock = self._locks[session_id]
        try:
            await asyncio.wait_for(lock.acquire(), timeout=Config.LOCK_TIMEOUT_SECONDS)
            yield
        except asyncio.TimeoutError:
            logger.error(f"Lock timeout for session {session_id}")
            raise Exception("Session temporarily unavailable")
        finally:
            if lock.locked():
                lock.release()
    
    def check_rate_limit(self, session_id: str) -> bool:
        """Check if session is within rate limits"""
        now = datetime.now(timezone.utc)
        minute_ago = now - timedelta(minutes=1)
        
        if session_id not in self._rate_limits:
            self._rate_limits[session_id] = []
        
        # Clean old entries
        self._rate_limits[session_id] = [
            timestamp for timestamp in self._rate_limits[session_id]
            if timestamp > minute_ago
        ]
        
        # Check limit
        if len(self._rate_limits[session_id]) >= Config.RATE_LIMIT_MESSAGES_PER_MINUTE:
            return False
        
        # Add current timestamp
        self._rate_limits[session_id].append(now)
        return True
    
    async def get_session_context(self, session_id: str) -> Optional[SessionContext]:
        """Get session context with automatic cleanup of expired sessions"""
        try:
            session_data = await get_user_session(session_id)
            if not session_data:
                return None
            
            # Check if session is expired
            created_at = datetime.fromisoformat(session_data.get('created_at', ''))
            if datetime.now(timezone.utc) - created_at > timedelta(hours=Config.SESSION_TTL_HOURS):
                logger.info(f"Session {session_id} expired, cleaning up")
                await self._cleanup_expired_session(session_id)
                return None
            
            # Convert to SessionContext
            extracted_data = ExtractedData(**session_data.get('extracted_data', {}))
            return SessionContext(
                session_id=session_id,
                platform=session_data.get('platform', 'web'),
                state=FlowState(session_data.get('state', 'initial')),
                extracted_data=extracted_data,
                message_count=session_data.get('message_count', 0),
                created_at=created_at,
                last_updated=datetime.fromisoformat(session_data.get('last_updated', '')),
                error_count=session_data.get('error_count', 0),
                rate_limit_count=session_data.get('rate_limit_count', 0),
                correlation_id=session_data.get('correlation_id', str(uuid.uuid4())[:8])
            )
        except Exception as e:
            logger.error(f"Error getting session context {session_id}: {str(e)}")
            return None
    
    async def save_session_context(self, context: SessionContext) -> bool:
        """Save session context atomically"""
        try:
            context.last_updated = datetime.now(timezone.utc)
            session_data = {
                'session_id': context.session_id,
                'platform': context.platform,
                'state': context.state.value,
                'extracted_data': asdict(context.extracted_data),
                'message_count': context.message_count,
                'created_at': context.created_at.isoformat(),
                'last_updated': context.last_updated.isoformat(),
                'error_count': context.error_count,
                'rate_limit_count': context.rate_limit_count,
                'correlation_id': context.correlation_id
            }
            return await save_user_session(context.session_id, session_data)
        except Exception as e:
            logger.error(f"Error saving session context {context.session_id}: {str(e)}")
            return False
    
    async def _cleanup_expired_session(self, session_id: str):
        """Clean up expired session"""
        try:
            await save_user_session(session_id, None)
            if session_id in self._locks:
                del self._locks[session_id]
            if session_id in self._rate_limits:
                del self._rate_limits[session_id]
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {str(e)}")

# =================== DATA EXTRACTOR ===================

class DataExtractor:
    """Intelligent data extraction from free-form text"""
    
    @staticmethod
    def extract_phone(text: str) -> Optional[str]:
        """Extract Brazilian phone number from text"""
        for pattern in DataPatterns.PHONE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                phone = re.sub(r'[^\d]', '', match.group())
                if 10 <= len(phone) <= 13:
                    return phone
        return None
    
    @staticmethod
    def extract_email(text: str) -> Optional[str]:
        """Extract email from text"""
        match = re.search(DataPatterns.EMAIL_PATTERN, text, re.IGNORECASE)
        return match.group() if match else None
    
    @staticmethod
    def extract_name(text: str) -> Optional[str]:
        """Extract name from text using various patterns"""
        for pattern in DataPatterns.NAME_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1) if match.groups() else match.group()
                # Validate name (at least 2 words, reasonable length)
                words = name.strip().split()
                if len(words) >= 2 and 4 <= len(name) <= 50:
                    return name.title()
        return None
    
    @staticmethod
    def detect_legal_area(text: str) -> Optional[str]:
        """Detect legal area from keywords"""
        text_lower = text.lower()
        
        penal_score = sum(1 for keyword in DataPatterns.LEGAL_AREAS['penal'] if keyword in text_lower)
        saude_score = sum(1 for keyword in DataPatterns.LEGAL_AREAS['saude'] if keyword in text_lower)
        
        if penal_score > saude_score and penal_score > 0:
            return "Direito Penal"
        elif saude_score > 0:
            return "Direito da Saúde"
        return None
    
    @staticmethod
    def detect_urgency(text: str) -> str:
        """Detect urgency level from text"""
        text_lower = text.lower()
        urgency_count = sum(1 for keyword in DataPatterns.URGENCY_KEYWORDS if keyword in text_lower)
        return "high" if urgency_count > 0 else "normal"
    
    @staticmethod
    def extract_all_data(text: str) -> ExtractedData:
        """Extract all possible data from text"""
        if not text or len(text.strip()) < 2:
            return ExtractedData()
        
        # Truncate if too long
        if len(text) > Config.MAX_MESSAGE_LENGTH:
            text = text[:Config.MAX_MESSAGE_LENGTH] + "..."
        
        extracted = ExtractedData(
            name=DataExtractor.extract_name(text),
            phone=DataExtractor.extract_phone(text),
            email=DataExtractor.extract_email(text),
            legal_area=DataExtractor.detect_legal_area(text),
            urgency_level=DataExtractor.detect_urgency(text),
            case_description=text.strip() if len(text.strip()) > 20 else None
        )
        
        # Calculate confidence score
        score = 0.0
        if extracted.name: score += 0.3
        if extracted.phone: score += 0.3
        if extracted.email: score += 0.2
        if extracted.legal_area: score += 0.2
        
        extracted.confidence_score = min(score, 1.0)
        return extracted

# =================== MESSAGE PROCESSOR ===================

class MessageProcessor:
    """Context-aware message processing"""
    
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
    
    def _get_personalized_greeting(self, extracted_data: ExtractedData) -> str:
        """Generate personalized greeting based on extracted data"""
        now = datetime.now()
        hour = now.hour
        
        if 5 <= hour < 12:
            greeting = "Bom dia"
        elif 12 <= hour < 18:
            greeting = "Boa tarde"
        else:
            greeting = "Boa noite"
        
        name_part = f", {extracted_data.name.split()[0]}" if extracted_data.name else ""
        urgency_part = " Entendo que sua situação é urgente." if extracted_data.urgency_level == "high" else ""
        
        return f"""{greeting}{name_part}! 👋

Bem-vindo ao m.lima Advogados Associados.{urgency_part}

Somos especialistas em Direito Penal e da Saúde, com mais de 1000 casos resolvidos e uma equipe experiente pronta para te ajudar.

Para que eu possa direcionar você ao advogado especialista ideal, preciso de algumas informações básicas."""
    
    def _generate_data_collection_message(self, context: SessionContext) -> str:
        """Generate intelligent data collection message"""
        data = context.extracted_data
        missing_items = []
        
        if not data.name:
            missing_items.append("seu nome completo")
        if not data.phone:
            missing_items.append("seu WhatsApp com DDD")
        if not data.email:
            missing_items.append("seu e-mail")
        if not data.legal_area:
            missing_items.append("a área jurídica (Penal ou Saúde)")
        
        if not missing_items:
            return self._generate_completion_message(context)
        
        if len(missing_items) == 1:
            return f"Para finalizar, preciso apenas de {missing_items[0]}:"
        elif len(missing_items) == 2:
            return f"Preciso ainda de {missing_items[0]} e {missing_items[1]}:"
        else:
            items_text = ", ".join(missing_items[:-1]) + f" e {missing_items[-1]}"
            return f"Para prosseguir, preciso de: {items_text}."
    
    def _generate_completion_message(self, context: SessionContext) -> str:
        """Generate completion message when all data is collected"""
        data = context.extracted_data
        name = data.name.split()[0] if data.name else "Cliente"
        
        return f"""Perfeito, {name}! ✅

Tenho todas as informações necessárias:
• Nome: {data.name}
• Contato: {data.phone} / {data.email}
• Área: {data.legal_area}

Nossa equipe especializada foi notificada e entrará em contato em breve. Você fez a escolha certa ao confiar no m.lima! 🤝"""
    
    async def process_message(self, message: str, context: SessionContext) -> Tuple[str, SessionContext]:
        """Process message with context awareness"""
        try:
            # Extract new data from message
            new_data = DataExtractor.extract_all_data(message)
            
            # Merge with existing data (new data takes precedence)
            merged_data = ExtractedData(
                name=new_data.name or context.extracted_data.name,
                phone=new_data.phone or context.extracted_data.phone,
                email=new_data.email or context.extracted_data.email,
                legal_area=new_data.legal_area or context.extracted_data.legal_area,
                urgency_level=new_data.urgency_level if new_data.urgency_level == "high" else context.extracted_data.urgency_level,
                case_description=new_data.case_description or context.extracted_data.case_description
            )
            
            # Update confidence score
            score = 0.0
            if merged_data.name: score += 0.3
            if merged_data.phone: score += 0.3
            if merged_data.email: score += 0.2
            if merged_data.legal_area: score += 0.2
            merged_data.confidence_score = min(score, 1.0)
            
            # Update context
            context.extracted_data = merged_data
            context.message_count += 1
            
            # Determine next state and response
            if context.state == FlowState.INITIAL:
                context.state = FlowState.COLLECTING_DATA
                response = self._get_personalized_greeting(merged_data)
                if merged_data.confidence_score < 1.0:
                    response += "\n\n" + self._generate_data_collection_message(context)
            elif context.state == FlowState.COLLECTING_DATA:
                if merged_data.confidence_score >= 1.0:
                    context.state = FlowState.COMPLETED
                    response = self._generate_completion_message(context)
                else:
                    response = self._generate_data_collection_message(context)
            elif context.state == FlowState.COMPLETED:
                name = merged_data.name.split()[0] if merged_data.name else "Cliente"
                response = f"Obrigado, {name}! Nossa equipe já foi notificada e entrará em contato em breve. 😊"
            else:
                # Error recovery
                context.state = FlowState.COLLECTING_DATA
                response = "Vamos continuar com seu atendimento. " + self._generate_data_collection_message(context)
            
            return response, context
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            context.error_count += 1
            context.state = FlowState.ERROR_RECOVERY
            return "Desculpe, houve um problema técnico. Vamos continuar seu atendimento.", context

# =================== ERROR RECOVERY ===================

class ErrorRecovery:
    """Intelligent error recovery that preserves user state"""
    
    @staticmethod
    def recover_from_error(context: SessionContext, error: Exception) -> Tuple[str, SessionContext]:
        """Recover from error while preserving user progress"""
        context.error_count += 1
        
        # Different recovery strategies based on error count
        if context.error_count == 1:
            # First error - gentle recovery
            context.state = FlowState.COLLECTING_DATA
            return "Houve um pequeno problema técnico, mas vamos continuar. Como posso ajudá-lo?", context
        elif context.error_count <= 3:
            # Multiple errors - more explicit recovery
            name = context.extracted_data.name.split()[0] if context.extracted_data.name else ""
            return f"Peço desculpas pelos problemas técnicos, {name}. Vamos prosseguir com seu atendimento.", context
        else:
            # Too many errors - fallback to basic service
            return "Estamos enfrentando dificuldades técnicas. Por favor, entre em contato pelo telefone (11) 91836-8812.", context

# =================== NOTIFICATION MANAGER ===================

class NotificationManager:
    """Handles notifications with retry logic and circuit breaker"""
    
    def __init__(self):
        self.failure_count = 0
        self.last_failure_time = None
        self.circuit_open = False
    
    async def notify_lawyers_with_retry(self, context: SessionContext) -> bool:
        """Notify lawyers with exponential backoff retry"""
        if self.circuit_open:
            if datetime.now(timezone.utc) - self.last_failure_time < timedelta(minutes=5):
                logger.warning("Circuit breaker open, skipping notification")
                return False
            else:
                self.circuit_open = False
                self.failure_count = 0
        
        for attempt in range(Config.NOTIFICATION_RETRY_ATTEMPTS):
            try:
                data = context.extracted_data
                result = await asyncio.wait_for(
                    lawyer_notification_service.notify_lawyers_of_new_lead(
                        lead_name=data.name,
                        lead_phone=data.phone,
                        category=data.legal_area,
                        additional_info={
                            "email": data.email,
                            "case_description": data.case_description,
                            "urgency_level": data.urgency_level,
                            "platform": context.platform,
                            "session_id": context.session_id,
                            "correlation_id": context.correlation_id
                        }
                    ),
                    timeout=Config.OPERATION_TIMEOUT_SECONDS
                )
                
                if result.get("success"):
                    self.failure_count = 0
                    logger.info(f"Lawyers notified successfully for session {context.session_id}")
                    return True
                else:
                    raise Exception(f"Notification failed: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                self.failure_count += 1
                self.last_failure_time = datetime.now(timezone.utc)
                
                if attempt < Config.NOTIFICATION_RETRY_ATTEMPTS - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Notification attempt {attempt + 1} failed, retrying in {wait_time}s: {str(e)}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"All notification attempts failed for session {context.session_id}: {str(e)}")
                    
                    # Open circuit breaker after too many failures
                    if self.failure_count >= 5:
                        self.circuit_open = True
                        logger.error("Circuit breaker opened due to repeated notification failures")
        
        return False

# =================== MAIN ORCHESTRATOR ===================

class IntelligentHybridOrchestrator:
    """Production-ready orchestrator with all improvements"""
    
    def __init__(self):
        self.session_manager = SessionManager()
        self.message_processor = MessageProcessor(self.session_manager)
        self.notification_manager = NotificationManager()
        self.gemini_available = True
        self.law_firm_number = Config.LAW_FIRM_NUMBER
    
    async def process_message(
        self, 
        message: str, 
        session_id: str, 
        phone_number: Optional[str] = None, 
        platform: str = "web"
    ) -> Dict[str, Any]:
        """Main message processing with comprehensive error handling"""
        correlation_id = str(uuid.uuid4())[:8]
        
        try:
            # Rate limiting check
            if not self.session_manager.check_rate_limit(session_id):
                logger.warning(f"Rate limit exceeded for session {session_id}")
                return {
                    "response_type": "rate_limited",
                    "session_id": session_id,
                    "response": "Muitas mensagens em pouco tempo. Aguarde um momento antes de enviar novamente.",
                    "correlation_id": correlation_id
                }
            
            # Use session lock to prevent race conditions
            async with self.session_manager.session_lock(session_id):
                # Get or create session context
                context = await self.session_manager.get_session_context(session_id)
                if not context:
                    context = SessionContext(
                        session_id=session_id,
                        platform=platform,
                        state=FlowState.INITIAL,
                        extracted_data=ExtractedData(),
                        correlation_id=correlation_id
                    )
                
                # Process message
                response, updated_context = await self.message_processor.process_message(message, context)
                
                # Handle completion
                if updated_context.state == FlowState.COMPLETED and updated_context.extracted_data.confidence_score >= 1.0:
                    # Save lead data
                    try:
                        await self._save_lead_data(updated_context)
                    except Exception as e:
                        logger.error(f"Error saving lead data: {str(e)}")
                    
                    # Notify lawyers (async, don't block response)
                    asyncio.create_task(self.notification_manager.notify_lawyers_with_retry(updated_context))
                    
                    # Send WhatsApp message if phone available
                    if updated_context.extracted_data.phone and platform == "web":
                        asyncio.create_task(self._send_whatsapp_confirmation(updated_context))
                
                # Save session context
                await self.session_manager.save_session_context(updated_context)
                
                return {
                    "response_type": f"{platform}_intelligent",
                    "session_id": session_id,
                    "response": response,
                    "state": updated_context.state.value,
                    "confidence_score": updated_context.extracted_data.confidence_score,
                    "message_count": updated_context.message_count,
                    "correlation_id": correlation_id,
                    "flow_completed": updated_context.state == FlowState.COMPLETED
                }
        
        except Exception as e:
            logger.error(f"Critical error in process_message (correlation_id: {correlation_id}): {str(e)}")
            
            # Try to recover context and provide meaningful response
            try:
                context = await self.session_manager.get_session_context(session_id)
                if context:
                    recovery_response, recovered_context = ErrorRecovery.recover_from_error(context, e)
                    await self.session_manager.save_session_context(recovered_context)
                    return {
                        "response_type": "error_recovery",
                        "session_id": session_id,
                        "response": recovery_response,
                        "correlation_id": correlation_id,
                        "error": "recovered"
                    }
            except Exception as recovery_error:
                logger.error(f"Error recovery failed (correlation_id: {correlation_id}): {str(recovery_error)}")
            
            # Final fallback
            return {
                "response_type": "system_error",
                "session_id": session_id,
                "response": "Estamos enfrentando dificuldades técnicas. Por favor, tente novamente em alguns minutos.",
                "correlation_id": correlation_id,
                "error": "system_failure"
            }
    
    async def handle_whatsapp_authorization(self, auth_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle WhatsApp authorization with improved error handling"""
        try:
            session_id = auth_data.get("session_id", "")
            phone_number = auth_data.get("phone_number", "")
            user_data = auth_data.get("user_data", {})
            
            # Create session context
            extracted_data = ExtractedData(
                name=user_data.get("name"),
                phone=phone_number,
                email=user_data.get("email")
            )
            
            context = SessionContext(
                session_id=session_id,
                platform="whatsapp",
                state=FlowState.INITIAL,
                extracted_data=extracted_data
            )
            
            await self.session_manager.save_session_context(context)
            
            # Send initial WhatsApp message
            initial_message = self._get_strategic_initial_message(
                user_data.get("name", "Cliente"), 
                session_id
            )
            
            phone_formatted = self._format_brazilian_phone(phone_number)
            whatsapp_number = f"{phone_formatted}@s.whatsapp.net"
            
            message_sent = await baileys_service.send_whatsapp_message(whatsapp_number, initial_message)
            
            return {
                "status": "authorization_processed",
                "session_id": session_id,
                "message_sent": message_sent
            }
            
        except Exception as e:
            logger.error(f"Error in WhatsApp authorization: {str(e)}")
            return {
                "status": "authorization_error",
                "error": str(e)
            }
    
    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """Get session context for external queries"""
        try:
            context = await self.session_manager.get_session_context(session_id)
            if not context:
                return {"exists": False}
            
            return {
                "exists": True,
                "session_id": session_id,
                "platform": context.platform,
                "state": context.state.value,
                "extracted_data": asdict(context.extracted_data),
                "message_count": context.message_count,
                "flow_completed": context.state == FlowState.COMPLETED,
                "correlation_id": context.correlation_id
            }
        except Exception as e:
            logger.error(f"Error getting session context: {str(e)}")
            return {"exists": False, "error": str(e)}
    
    async def get_overall_service_status(self) -> Dict[str, Any]:
        """Get comprehensive service status"""
        try:
            firebase_status = await get_firebase_service_status()
            
            return {
                "overall_status": "active" if firebase_status.get("status") == "active" else "degraded",
                "firebase_status": firebase_status,
                "features": {
                    "intelligent_data_extraction": True,
                    "flexible_conversation_flow": True,
                    "error_recovery": True,
                    "rate_limiting": True,
                    "session_management": True,
                    "notification_retry": True
                },
                "configuration": {
                    "session_ttl_hours": Config.SESSION_TTL_HOURS,
                    "rate_limit_per_minute": Config.RATE_LIMIT_MESSAGES_PER_MINUTE,
                    "operation_timeout": Config.OPERATION_TIMEOUT_SECONDS
                }
            }
        except Exception as e:
            logger.error(f"Error getting service status: {str(e)}")
            return {
                "overall_status": "error",
                "error": str(e)
            }
    
    # =================== HELPER METHODS ===================
    
    def _format_brazilian_phone(self, phone: str) -> str:
        """Format Brazilian phone number for WhatsApp"""
        if not phone:
            return ""
        
        phone_clean = ''.join(filter(str.isdigit, str(phone)))
        
        if phone_clean.startswith("55"):
            return phone_clean
        elif len(phone_clean) == 11:
            return f"55{phone_clean}"
        elif len(phone_clean) == 10:
            ddd = phone_clean[:2]
            number = phone_clean[2:]
            if number[0] in ['6', '7', '8', '9']:
                number = f"9{number}"
            return f"55{ddd}{number}"
        else:
            return f"55{phone_clean}"
    
    def _get_strategic_initial_message(self, user_name: str, session_id: str) -> str:
        """Generate strategic initial WhatsApp message"""
        first_name = user_name.split()[0] if user_name else "Cliente"
        
        return f"""Olá {first_name}! 👋

Obrigado por entrar em contato com o escritório m.lima através do nosso site.

Nossa equipe especializada está pronta para te ajudar com seu caso jurídico.

Para darmos continuidade ao seu atendimento personalizado, responda esta mensagem com detalhes sobre sua situação.

🆔 Sessão: {session_id}

---
✉️ m.lima Advogados Associados
📱 Atendimento prioritário ativado"""
    
    async def _save_lead_data(self, context: SessionContext):
        """Save lead data to Firebase"""
        try:
            data = context.extracted_data
            answers = []
            
            if data.name:
                answers.append({"id": 1, "field": "name", "answer": data.name})
            if data.phone:
                answers.append({"id": 2, "field": "phone", "answer": data.phone})
            if data.email:
                answers.append({"id": 3, "field": "email", "answer": data.email})
            if data.legal_area:
                answers.append({"id": 4, "field": "legal_area", "answer": data.legal_area})
            if data.case_description:
                answers.append({"id": 5, "field": "case_description", "answer": data.case_description})
            
            lead_id = await save_lead_data({
                "answers": answers,
                "platform": context.platform,
                "session_id": context.session_id,
                "confidence_score": data.confidence_score,
                "urgency_level": data.urgency_level,
                "correlation_id": context.correlation_id
            })
            
            logger.info(f"Lead saved with ID: {lead_id} (correlation_id: {context.correlation_id})")
            
        except Exception as e:
            logger.error(f"Error saving lead data: {str(e)}")
            raise
    
    async def _send_whatsapp_confirmation(self, context: SessionContext):
        """Send WhatsApp confirmation message"""
        try:
            data = context.extracted_data
            phone_formatted = self._format_brazilian_phone(data.phone)
            whatsapp_number = f"{phone_formatted}@s.whatsapp.net"
            
            first_name = data.name.split()[0] if data.name else "Cliente"
            message = f"""Perfeito, {first_name}! ✅

Suas informações foram registradas com sucesso:
• Nome: {data.name}
• Área: {data.legal_area}

Nossa equipe especializada foi notificada e entrará em contato em breve.

Você fez a escolha certa ao confiar no m.lima! 🤝

---
✉️ m.lima Advogados Associados"""
            
            await baileys_service.send_whatsapp_message(whatsapp_number, message)
            logger.info(f"WhatsApp confirmation sent to {phone_formatted}")
            
        except Exception as e:
            logger.error(f"Error sending WhatsApp confirmation: {str(e)}")

# =================== GLOBAL INSTANCE ===================

# Global instance with backward compatibility
intelligent_orchestrator = IntelligentHybridOrchestrator()
hybrid_orchestrator = intelligent_orchestrator  # Alias for compatibility

# Background task for session cleanup (would be implemented as a separate service in production)
async def cleanup_expired_sessions():
    """Background task to clean up expired sessions"""
    # This would typically be implemented as a separate Cloud Function or cron job
    pass