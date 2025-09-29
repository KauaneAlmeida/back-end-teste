"""
Baileys WhatsApp Service

This service communicates with the dedicated `whatsapp_bot` container over HTTP.
It handles message sending, status checking, and connection management.
Clean service focused only on message dispatch - no business logic.
"""
import requests
import logging
import asyncio
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)
    
class BaileysWhatsAppService:
    def __init__(self, base_url: str = None):
        # ✅ ENDPOINT CORRETO DA VM
        self.base_url = base_url or os.getenv("WHATSAPP_BOT_URL", "http://34.27.244.115:8081")
        self.timeout = 10
        self.max_retries = 2
        self.initialized = False
        self.connection_healthy = False

    async def initialize(self):
        """Initialize connection to WhatsApp bot service."""
        if self.initialized:
            logger.info("Baileys service already initialized")
            return True

        try:
            logger.info(f"🔌 Inicializando conexão com VM Baileys: {self.base_url}")

            try:
                await asyncio.wait_for(
                    self._attempt_connection(),
                    timeout=20.0
                )
                return True
            except asyncio.TimeoutError:
                logger.warning("⏰ Timeout na inicialização da VM Baileys")
                self.initialized = False
                return False

        except Exception as e:
            logger.error(f"❌ Erro ao inicializar VM Baileys: {str(e)}")
            self.initialized = False
            return False

    async def _attempt_connection(self):
        """Attempt connection with retries."""
        for attempt in range(self.max_retries):
            try:
                loop = asyncio.get_event_loop()
                
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        f"{self.base_url}/health", 
                        timeout=8
                    )
                )
                
                if response.status_code == 200:
                    logger.info("✅ VM Baileys está acessível")
                    self.initialized = True
                    self.connection_healthy = True
                    return True
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"⚠️ Tentativa {attempt + 1} falhou, tentando novamente...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"❌ Falha após {self.max_retries} tentativas: {str(e)}")

        return False

    async def cleanup(self):
        """Cleanup resources."""
        logger.info("🧹 Limpando recursos do serviço WhatsApp")
        self.initialized = False
        self.connection_healthy = False

    async def send_whatsapp_message(self, phone_number: str, message: str) -> bool:
        """
        ✅ ENVIO DE MENSAGEM WHATSAPP CORRIGIDO
        
        Função principal chamada pelo Orchestrator
        Corrigido: formato do número, endpoint, logs detalhados
        """
        try:
            # ✅ CORREÇÃO: NÃO ADICIONAR @s.whatsapp.net (VM já faz isso)
            clean_phone = ''.join(filter(str.isdigit, phone_number))
            if not clean_phone.startswith("55"):
                clean_phone = f"55{clean_phone}"
            
            # ✅ PAYLOAD CORRETO PARA A VM
            payload = {
                "phone_number": clean_phone,  # Apenas o número limpo
                "message": message
            }
            
            logger.info(f"📤 Enviando mensagem WhatsApp")
            logger.info(f"📱 Número: {clean_phone}")
            logger.info(f"💬 Mensagem: {message[:100]}{'...' if len(message) > 100 else ''}")
            logger.info(f"🔗 Endpoint: {self.base_url}/send-message")
            logger.info(f"📦 Payload: {payload}")


            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        f"{self.base_url}/send-message",
                        json=payload,
                        timeout=self.timeout,
                        headers={"Content-Type": "application/json"}
                    )
                ),
                timeout=15.0
            )

            # ✅ LOGS DETALHADOS DA RESPOSTA DA VM
            logger.info(f"📊 Resposta da VM: Status {response.status_code}")
            logger.info(f"📄 Resposta da VM: Body {response.text}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"📋 JSON da resposta: {result}")
                    
                    if result.get("success") or result.get("status") == "success":
                        logger.info(f"✅ Mensagem WhatsApp enviada com sucesso para {clean_phone}")
                        self.connection_healthy = True
                        return True
                    else:
                        logger.error(f"❌ VM rejeitou mensagem: {result.get('error', 'Erro desconhecido')}")
                        return False
                except Exception as json_error:
                    logger.error(f"❌ Erro ao parsear JSON da VM: {str(json_error)}")
                    logger.error(f"📄 Resposta raw: {response.text}")
                    # Se status 200 mas JSON inválido, considerar sucesso
                    self.connection_healthy = True
                    return True
            else:
                logger.error(f"❌ VM retornou erro HTTP {response.status_code}")
                logger.error(f"📄 Resposta: {response.text}")
                return False

        except asyncio.TimeoutError:
            logger.error("⏰ Timeout ao enviar mensagem WhatsApp para VM")
            self.connection_healthy = False
            return False
        except requests.exceptions.ConnectionError:
            logger.error("🔌 Falha de conexão com a VM Baileys")
            self.connection_healthy = False
            return False
        except Exception as e:
            logger.error(f"❌ Erro inesperado ao enviar WhatsApp: {str(e)}")
            return False

    async def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status from whatsapp_bot API."""
        try:
            loop = asyncio.get_event_loop()
            
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        f"{self.base_url}/health",
                        timeout=5
                    )
                ),
                timeout=8.0
            )

            if response.status_code == 200:
                data = response.json()
                self.connection_healthy = True
                return {
                    "status": "connected" if data.get("isConnected") else "disconnected",
                    "service": "baileys_whatsapp",
                    "connected": data.get("isConnected", False),
                    "has_qr": data.get("hasQR", False),
                    "phone_number": data.get("phoneNumber", "unknown"),
                    "timestamp": data.get("timestamp"),
                    "qr_url": f"http://34.27.244.115:8081/qr" if not data.get("isConnected") else None,
                    "service_healthy": True
                }
            else:
                self.connection_healthy = False
                return {
                    "status": "error", 
                    "service": "baileys_whatsapp", 
                    "connected": False,
                    "service_healthy": False
                }

        except asyncio.TimeoutError:
            logger.warning("⏰ Timeout no status check da VM")
            self.connection_healthy = False
            return {
                "status": "timeout", 
                "service": "baileys_whatsapp", 
                "connected": False,
                "service_healthy": False,
                "error": "Status check timed out"
            }
        except requests.exceptions.ConnectionError:
            self.connection_healthy = False
            return {
                "status": "service_unavailable", 
                "service": "baileys_whatsapp", 
                "connected": False,
                "service_healthy": False,
                "error": "Service unavailable"
            }
        except Exception as e:
            logger.error(f"❌ Erro ao obter status da VM: {str(e)}")
            self.connection_healthy = False
            return {
                "status": "error", 
                "service": "baileys_whatsapp", 
                "connected": False, 
                "service_healthy": False,
                "error": str(e)
            }

    async def check_health(self) -> Dict[str, Any]:
        """Quick health check of WhatsApp bot service."""
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: requests.get(f"{self.base_url}/health", timeout=5)
                ),
                timeout=7.0
            )
            
            result = response.json() if response.status_code == 200 else {"status": "unhealthy"}
            self.connection_healthy = result.get("status") == "healthy"
            return result
            
        except Exception as e:
            self.connection_healthy = False
            return {"status": "unhealthy", "error": str(e)}

    def is_healthy(self) -> bool:
        """Quick health check without async call."""
        return self.connection_healthy and self.initialized

# Global instance
baileys_service = BaileysWhatsAppService()

# Simple wrappers for backward compatibility
async def send_baileys_message(phone_number: str, message: str) -> bool:
    """Wrapper function - delegates to baileys_service."""
    return await baileys_service.send_whatsapp_message(phone_number, message)

async def get_baileys_status() -> Dict[str, Any]:
    """Wrapper function - delegates to baileys_service."""
    return await baileys_service.get_connection_status()



