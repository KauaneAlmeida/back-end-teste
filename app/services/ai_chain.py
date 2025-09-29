"""
AI Chain Service with LangChain + Gemini Integration

This module provides LangChain-based conversation management with Google Gemini.
It handles conversation memory, system prompts, and AI response generation.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

# LangChain imports
from langchain.memory import ConversationBufferWindowMemory
from langchain.schema import BaseMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser

# Configure logging
logger = logging.getLogger(__name__)

# Global conversation memories (session-based)
conversation_memories: Dict[str, ConversationBufferWindowMemory] = {}

# AI configuration
AI_CONFIG_FILE = "app/ai_schema.json"
DEFAULT_MODEL = "gemini-1.5-flash"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 1000
MEMORY_WINDOW = 10


def load_ai_config() -> Dict[str, Any]:
    """
    Load AI configuration from JSON file.
    """
    try:
        if os.path.exists(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info("✅ AI configuration loaded from file")
                return config
        else:
            logger.warning("⚠️ AI config file not found, using defaults")
            return get_default_ai_config()
    except Exception as e:
        logger.error(f"❌ Error loading AI config: {str(e)}")
        return get_default_ai_config()


def get_default_ai_config() -> Dict[str, Any]:
    """
    Get default AI configuration.
    """
    return {
        "system_prompt": """Você é um assistente jurídico especializado de um escritório de advocacia no Brasil.

DIRETRIZES IMPORTANTES:
- Responda SEMPRE em português brasileiro
- Mantenha respostas profissionais, concisas e humanizadas
- NÃO forneça aconselhamento jurídico específico (respeitar OAB)
- Demonstre empatia e urgência quando apropriado
- Use linguagem natural, curta e clara (não pareça robótico)
- Reforce a autoridade do escritório
- Crie valor percebido antes da transferência
- Capture gatilhos de necessidade (prazos, audiências, urgência)

CONTEXTO ESPECIAL:
- Você conduz o lead até deixá-lo pronto para o advogado
- Use as informações coletadas para personalizar respostas
- Adapte o tom baseado na plataforma ([Platform: WEB] ou [Platform: WHATSAPP])
- Foque em qualificar e aquecer o lead

ÁREAS DE ESPECIALIZAÇÃO:
- Direito Penal
- Direito Trabalhista  
- Direito Civil
- Direito de Família
- Saúde/Liminares
- Outras áreas

FORMATO DE RESPOSTA:
- Para WhatsApp: Máximo 2 parágrafos, linguagem mais direta
- Para Web: Máximo 3 parágrafos, pode ser mais detalhado
- Sempre termine preparando para a transferência quando apropriado
- Use emojis moderadamente no WhatsApp

TAREFAS ESPECIAIS:
- Transmitir autoridade e confiança desde o início
- Coletar dados essenciais de forma natural
- Qualificar a área jurídica corretamente
- Capturar urgência e contexto do caso
- Preparar o lead para transferência humanizada

Você tem acesso ao histórico da conversa para fornecer respostas contextualizadas.""",
        "ai_config": {
            "model": DEFAULT_MODEL,
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "memory_window": MEMORY_WINDOW,
            "timeout": 30
        }
    }


def get_conversation_memory(session_id: str) -> ConversationBufferWindowMemory:
    """
    Get or create conversation memory for a session.
    """
    if session_id not in conversation_memories:
        conversation_memories[session_id] = ConversationBufferWindowMemory(
            k=MEMORY_WINDOW,
            return_messages=True,
            memory_key="chat_history"
        )
        logger.info(f"🧠 Created new conversation memory for session: {session_id}")
    
    return conversation_memories[session_id]


def clear_conversation_memory(session_id: str) -> bool:
    """
    Clear conversation memory for a specific session.
    """
    try:
        if session_id in conversation_memories:
            conversation_memories[session_id].clear()
            logger.info(f"🧹 Cleared conversation memory for session: {session_id}")
            return True
        else:
            logger.warning(f"⚠️ No memory found for session: {session_id}")
            return False
    except Exception as e:
        logger.error(f"❌ Error clearing memory for session {session_id}: {str(e)}")
        return False


def get_conversation_summary(session_id: str) -> str:
    """
    Get a summary of the conversation for a session.
    """
    try:
        if session_id in conversation_memories:
            memory = conversation_memories[session_id]
            messages = memory.chat_memory.messages
            
            if not messages:
                return "No conversation history"
            
            # Create a simple summary
            summary_parts = []
            for message in messages[-6:]:  # Last 6 messages
                if isinstance(message, HumanMessage):
                    summary_parts.append(f"User: {message.content[:100]}...")
                elif isinstance(message, AIMessage):
                    summary_parts.append(f"AI: {message.content[:100]}...")
            
            return "\n".join(summary_parts)
        else:
            return "No conversation found"
    except Exception as e:
        logger.error(f"❌ Error getting conversation summary: {str(e)}")
        return "Error retrieving summary"


class AIOrchestrator:
    """
    Main AI orchestrator using LangChain + Gemini.
    """
    
    def __init__(self):
        self.config = load_ai_config()
        self.ai_config = self.config.get("ai_config", {})
        self.system_prompt = self.config.get("system_prompt", "")
        self.llm = None
        self.chain = None
        self._initialize_llm()
    
    def _initialize_llm(self):
        """
        Initialize the LangChain LLM with Gemini.
        """
        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.error("❌ GEMINI_API_KEY not found in environment variables")
                return
            
            # Initialize Gemini LLM
            self.llm = ChatGoogleGenerativeAI(
                model=self.ai_config.get("model", DEFAULT_MODEL),
                temperature=self.ai_config.get("temperature", DEFAULT_TEMPERATURE),
                max_tokens=self.ai_config.get("max_tokens", DEFAULT_MAX_TOKENS),
                google_api_key=api_key
            )
            
            # Create the conversation chain
            self._create_chain()
            
            logger.info(f"✅ AI Orchestrator initialized with model: {self.ai_config.get('model', DEFAULT_MODEL)}")
            
        except Exception as e:
            logger.error(f"❌ Error initializing AI Orchestrator: {str(e)}")
            self.llm = None
            self.chain = None
    
    def _create_chain(self):
        """
        Create the LangChain conversation chain.
        """
        try:
            if not self.llm:
                logger.error("❌ Cannot create chain: LLM not initialized")
                return
            
            # Create the prompt template
            prompt = ChatPromptTemplate.from_messages([
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}")
            ])
            
            # Create the chain
            self.chain = (
                RunnablePassthrough.assign(
                    chat_history=lambda x: x["chat_history"]
                )
                | prompt
                | self.llm
                | StrOutputParser()
            )
            
            logger.info("✅ LangChain conversation chain created")
            
        except Exception as e:
            logger.error(f"❌ Error creating conversation chain: {str(e)}")
            self.chain = None
    
    async def generate_response(
        self, 
        message: str, 
        session_id: str = "default",
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate AI response using LangChain + Gemini.
        """
        try:
            if not self.chain:
                logger.error("❌ AI chain not available")
                return "Desculpe, o serviço de IA não está disponível no momento."
            
            # Get conversation memory
            memory = get_conversation_memory(session_id)
            
            # Add platform context to message if provided
            enhanced_message = message
            if context and context.get("platform"):
                platform = context["platform"].upper()
                enhanced_message = f"[Platform: {platform}] {message}"
            
            # Prepare input for the chain
            chain_input = {
                "input": enhanced_message,
                "chat_history": memory.chat_memory.messages
            }
            
            logger.info(f"🤖 Generating AI response for session: {session_id}")
            
            # Generate response
            response = await self.chain.ainvoke(chain_input)
            
            # Save to memory
            memory.save_context(
                {"input": enhanced_message},
                {"output": response}
            )
            
            logger.info(f"✅ AI response generated for session: {session_id}")
            return response
            
        except Exception as e:
            logger.error(f"❌ Error generating AI response: {str(e)}")
            return "Desculpe, ocorreu um erro ao processar sua mensagem. Como posso ajudá-lo?"
    
    def is_available(self) -> bool:
        """
        Check if AI service is available.
        """
        return self.llm is not None and self.chain is not None


# Global AI orchestrator instance
ai_orchestrator = AIOrchestrator()


# Main service functions
async def process_chat_message(
    message: str, 
    session_id: str = "default",
    context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Process chat message using LangChain + Gemini.
    """
    try:
        logger.info(f"📨 Processing chat message for session: {session_id}")
        
        if not ai_orchestrator.is_available():
            logger.error("❌ AI orchestrator not available")
            return "Desculpe, o serviço de IA não está disponível no momento. Como posso ajudá-lo?"
        
        response = await ai_orchestrator.generate_response(message, session_id, context)
        return response
        
    except Exception as e:
        logger.error(f"❌ Error in process_chat_message: {str(e)}")
        return "Desculpe, ocorreu um erro ao processar sua mensagem. Tente novamente."


async def get_ai_service_status() -> Dict[str, Any]:
    """
    Get AI service status.
    """
    try:
        api_key_configured = bool(os.getenv("GEMINI_API_KEY"))
        ai_available = ai_orchestrator.is_available()
        
        return {
            "service": "ai_chain_langchain_gemini",
            "status": "active" if ai_available else "configuration_required",
            "ai_available": ai_available,
            "api_key_configured": api_key_configured,
            "model": ai_orchestrator.ai_config.get("model", DEFAULT_MODEL),
            "memory_sessions": len(conversation_memories),
            "features": [
                "langchain_integration",
                "conversation_memory",
                "google_gemini_api",
                "session_management",
                "context_awareness",
                "platform_adaptation"
            ],
            "configuration_notes": [
                "Set GEMINI_API_KEY environment variable",
                "Configure ai_schema.json for custom prompts"
            ] if not api_key_configured else []
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting AI service status: {str(e)}")
        return {
            "service": "ai_chain_langchain_gemini",
            "status": "error",
            "error": str(e),
            "ai_available": False
        }


# Initialize on import
logger.info("🚀 AI Chain service loaded with LangChain + Gemini integration")