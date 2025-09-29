<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>💬 Chat Advocacia — Escritório X!</title>
  <style>
    body {
      font-family: 'Poppins', sans-serif;
      margin: 0;
      padding: 0;
      height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      background: url('https://imgur.com/FKXnrb1.png') no-repeat center center fixed;
      background-size: cover;
    }
    .chat-container {
      max-width: 500px;
      width: 100%;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 15px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.6);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      height: 80vh;
      backdrop-filter: blur(10px);
      transition: all 0.3s ease;
    }
    .chat-header {
      background: #bd9b68;
      color: white;
      padding: 15px;
      text-align: center;
      font-size: 20px;
      font-weight: bold;
      letter-spacing: 1px;
      border-bottom: 2px solid ;
    }
    .messages {
      flex: 1;
      padding: 15px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .message {
      display: flex;
      align-items: flex-end;
      gap: 8px;
    }
    .message.user { justify-content: flex-end; }
    .bubble {
      padding: 10px 15px;
      border-radius: 15px;
      max-width: 70%;
      font-size: 14px;
      line-height: 1.4;
      position: relative;
    }
    .user .bubble {
      background: #492519;
      color: white;
      border-bottom-right-radius: 0;
    }
    .bot .bubble {
      background: #4682b4;
      color: white;
      border-bottom-left-radius: 0;
    }
    .avatar {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: 2px solid white;
    }
    .input-area {
      display: flex;
      border-top: 2px solid #444;
      padding: 10px;
      background: rgba(44, 44, 44, 0.9);
    }
    .input-area input {
      flex: 1;
      border: none;
      border-radius: 20px;
      padding: 12px;
      font-size: 14px;
      outline: none;
      background: #444;
      color: white;
    }
    .input-area input::placeholder { color: #bbb; }
    .input-area button {
      margin-left: 8px;
      background: #ff9800;
      border: none;
      border-radius: 20px;
      padding: 10px 20px;
      color: white;
      font-size: 14px;
      cursor: pointer;
      transition: 0.2s;
    }
    .input-area button:hover { background: #e07d00; }
    .chat-reset-btn {
      background: #28a745;
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 15px;
      font-size: 12px;
      cursor: pointer;
      margin-left: 10px;
      transition: 0.2s;
    }
    .chat-reset-btn:hover { background: #218838; }
    .chat-completed {
      background: rgba(40, 167, 69, 0.1);
      border: 2px solid #28a745;
      border-radius: 10px;
      padding: 15px;
      margin: 10px 0;
      text-align: center;
    }
    @media (max-width: 600px) {
      .chat-container { width: 90%; height: 70vh; border-radius: 20px; margin: auto; }
      .chat-header { font-size: 16px; padding: 10px; }
      .bubble { font-size: 13px; max-width: 80%; }
      .input-area input { font-size: 13px; padding: 10px; }
      .input-area button { padding: 8px 16px; font-size: 13px; }
    }
  </style>
</head>
<body>
  <div class="chat-container">
    <div class="chat-header">💬 Chat Advocacia — Escritório X!</div>
    <div id="messages" class="messages">
      <div class="message bot">
        <div class="bubble">Carregando...</div>
        <img src="https://imgur.com/z9lvA3Z.png" class="avatar" alt="Bot">
        <div class="bubble"> Bem-vindo ao escritório, pronto para conversar?</div>
      </div>
    </div>
    <div class="input-area">
      <input id="messageInput" type="text" placeholder="Digite sua mensagem... ⚖️">
      <button onclick="sendMessage()">Enviar</button>
      <button id="resetBtn" class="chat-reset-btn" onclick="resetChat()" style="display: none;">Nova Conversa</button>
    </div>
  </div>

  <script>
    // 🔗 URL do backend
    const API_BASE_URL = 'https://law-firm-backend-936902782519-936902782519.us-central1.run.app';
    
    // 🎯 Estado do chat
    let chatState = {
      sessionId: null,
      isCompleted: false,
      messageCount: 0,
      hasStarted: false
    };

    // 🔄 Função para resetar o chat
    function resetChat() {
      console.log('🔄 Resetando chat...');
      
      // Limpar estado
      chatState = {
        sessionId: null,
        isCompleted: false,
        messageCount: 0,
        hasStarted: false
      };
      
      // Limpar localStorage
      localStorage.removeItem('chat_session_id');
      
      // Limpar mensagens
      const messagesDiv = document.getElementById('messages');
      messagesDiv.innerHTML = `
        <div class="message bot">
          <img src="https://imgur.com/z9lvA3Z.png" class="avatar" alt="Bot">
          <div class="bubble">Carregando...</div>
        </div>
      `;
      
      // Reabilitar input
      const input = document.getElementById('messageInput');
      const sendBtn = document.querySelector('button[onclick="sendMessage()"]');
      
      input.disabled = false;
      input.placeholder = "Digite sua mensagem... ⚖️";
      sendBtn.disabled = false;
      
      // Inicializar conversa automaticamente
      setTimeout(() => initializeChat(), 500);
      
      console.log('✅ Chat resetado com sucesso');
    }
    
    // 🎯 Função para inicializar chat com saudação personalizada
    async function initializeChat() {
      try {
        console.log('🚀 Inicializando chat com saudação personalizada...');
        
        const response = await fetch(`${API_BASE_URL}/api/v1/conversation/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });

        if (response.ok) {
          const data = await response.json();
          
          // Atualizar primeira mensagem com saudação personalizada
          const firstMessage = document.querySelector('.message.bot .bubble');
          if (firstMessage) {
            firstMessage.textContent = data.response || data.question || "Olá! Como posso ajudá-lo?";
          }
          
          if (data.session_id) {
            chatState.sessionId = data.session_id;
            localStorage.setItem('chat_session_id', data.session_id);
          }
          
          chatState.hasStarted = true;
          console.log('✅ Chat inicializado com sucesso');
        } else {
          console.error('❌ Erro ao inicializar chat');
          const firstMessage = document.querySelector('.message.bot .bubble');
          if (firstMessage) {
            firstMessage.textContent = "Olá! Como posso ajudá-lo hoje?";
          }
        }
      } catch (err) {
        console.error('❌ Erro na inicialização:', err);
        const firstMessage = document.querySelector('.message.bot .bubble');
        if (firstMessage) {
          firstMessage.textContent = "Olá! Como posso ajudá-lo hoje?";
        }
      }
    }

    function addMessage(text, sender = 'user') {
      const messagesDiv = document.getElementById('messages');
      const messageDiv = document.createElement('div');
      messageDiv.className = `message ${sender}`;

      const avatar = document.createElement('img');
      avatar.className = 'avatar';
      avatar.src = sender === 'user' 
        ? 'https://imgur.com/P9aCUJC.png'
        : 'https://imgur.com/z9lvA3Z.png';
      avatar.alt = sender;

      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.textContent = text;

      if (sender === 'user') {
        messageDiv.appendChild(bubble);
        messageDiv.appendChild(avatar);
      } else {
        messageDiv.appendChild(avatar);
        messageDiv.appendChild(bubble);
      }

      messagesDiv.appendChild(messageDiv);
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
      
      chatState.messageCount++;
    }

    async function sendMessage() {
      const input = document.getElementById('messageInput');
      const text = input.value.trim();
      if (!text) return;
      
      addMessage(text, 'user');
      input.value = '';
      
        console.log('🆕 Nova sessão criada:', chatState.sessionId);
      }

      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/conversation/respond`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            message: text, 
            session_id: chatState.sessionId
          })
        });

        if (!response.ok) throw new Error('Erro na API');
        const data = await response.json();

        // Atualizar sessionId se retornado
        if (data.session_id && data.session_id !== chatState.sessionId) {
          chatState.sessionId = data.session_id;
          localStorage.setItem('chat_session_id', data.session_id);
        }

        const botMessage = data.response || data.question || data.reply || "🤔 O bot ficou em silêncio...";
        addMessage(botMessage, 'bot');
        
        // Verificar se conversa foi finalizada
        if (data.flow_completed || data.lawyers_notified || 
            (data.response && data.response.includes('Nossa equipe entrará em contato'))) {
          console.log('🎯 Conversa finalizada detectada');
          setTimeout(() => markChatCompleted(), 1000);
        }

      } catch (err) {
        console.error('API Error:', err);
        addMessage("⚠️ Erro de conexão com o backend.", 'bot');
      }
    }

    window.addEventListener('load', async () => {
      console.log('🚀 Inicializando chat...');
      
      // Verificar se há sessão salva
      const savedSessionId = localStorage.getItem('chat_session_id');
      if (savedSessionId) {
        console.log('📋 Sessão encontrada:', savedSessionId);
        chatState.sessionId = savedSessionId;
        
        // Verificar status da sessão
        try {
          const statusResponse = await fetch(`${API_BASE_URL}/api/v1/conversation/status/${savedSessionId}`);
          if (statusResponse.ok) {
            const statusData = await statusResponse.json();
            if (statusData.status_info && statusData.status_info.flow_completed) {
              console.log('📋 Sessão anterior finalizada - permitindo nova conversa');
              resetChat();
              return;
            }
          }
        } catch (e) {
          console.log('⚠️ Erro ao verificar status - iniciando nova sessão');
          resetChat();
          return;
        }
      }
      
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/conversation/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });

        if (response.ok) {
          const data = await response.json();
          if (data.session_id && !chatState.sessionId) {
            chatState.sessionId = data.session_id;
            localStorage.setItem('chat_session_id', data.session_id);
          }
          if (data.question) {
            addMessage(data.question, 'bot');
          } else if (data.response) {
            addMessage(data.response, 'bot');
          }
        }
      } catch (err) {
        console.error('❌ Falha ao inicializar conversa:', err);
      }
    });

    document.getElementById('messageInput').addEventListener('keypress', e => {
      if (e.key === 'Enter' && !chatState.isCompleted) {
        sendMessage();
      }
    });
  </script>
</body>
</html>
