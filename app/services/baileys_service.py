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
        self.base_url = base_url or os.getenv("WHATSAPP_BOT_URL", "http://law_firm_whatsapp_bot:3000")
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
            logger.info(f"Checking WhatsApp bot service at {self.base_url}")

            try:
                await asyncio.wait_for(
                    self._attempt_connection(),
                    timeout=20.0
                )
                return True
            except asyncio.TimeoutError:
                logger.warning("WhatsApp bot initialization timed out")
                self.initialized = False
                return False

        except Exception as e:
            logger.error(f"Error initializing WhatsApp bot: {str(e)}")
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
                    logger.info("WhatsApp bot service is reachable")
                    self.initialized = True
                    self.connection_healthy = True
                    return True
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Connection attempt {attempt + 1} failed, retrying...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"Failed to connect after {self.max_retries} attempts: {str(e)}")

        return False

    async def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up WhatsApp service resources")
        self.initialized = False
        self.connection_healthy = False

    async def send_whatsapp_message(self, phone_number: str, message: str) -> bool:
        """Send WhatsApp message - core function called by Orchestrator."""
        try:
            # Format phone for WhatsApp
            if "@s.whatsapp.net" not in phone_number:
                clean_phone = ''.join(filter(str.isdigit, phone_number))
                if not clean_phone.startswith("55"):
                    clean_phone = f"55{clean_phone}"
                phone_number = f"{clean_phone}@s.whatsapp.net"

            payload = {"phone_number": phone_number, "message": message}
            logger.info(f"Sending WhatsApp message to {phone_number[:15]}...")

            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        f"{self.base_url}/send-message",
                        json=payload,
                        timeout=self.timeout
                    )
                ),
                timeout=15.0
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    logger.info(f"WhatsApp message sent successfully to {phone_number[:15]}")
                    self.connection_healthy = True
                    return True
                else:
                    logger.error(f"WhatsApp API error: {result.get('error', 'Unknown error')}")
                    return False
            else:
                logger.error(f"WhatsApp API failed with {response.status_code}: {response.text}")
                return False

        except asyncio.TimeoutError:
            logger.error("WhatsApp message request timed out")
            self.connection_healthy = False
            return False
        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to WhatsApp bot service")
            self.connection_healthy = False
            return False
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {str(e)}")
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
                    "qr_url": f"{self.base_url}/qr" if not data.get("isConnected") else None,
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
            logger.warning("WhatsApp status check timed out")
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
            logger.error(f"Error getting WhatsApp status: {str(e)}")
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



