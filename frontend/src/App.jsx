import React, { useState, useEffect, useRef, useCallback } from 'react';
import Header from './components/Header';
import ChatPanel from './components/ChatPanel';
import DialogsPanel from './components/DialogsPanel';
import LiveViewport from './components/LiveViewport';
import LogDrawer from './components/LogDrawer';
import SettingsModal from './components/SettingsModal';
import MemoryModal from './components/MemoryModal';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary перехватил ошибку UI:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          backgroundColor: '#0b0f19',
          color: '#f8fafc',
          fontFamily: 'Inter, sans-serif',
          padding: '20px',
          textAlign: 'center'
        }}>
          <h2 style={{ fontSize: '20px', marginBottom: '10px', color: '#ef4444' }}>
            Произошла ошибка интерфейса
          </h2>
          <p style={{ fontSize: '13px', color: '#94a3b8', maxWidth: '500px', marginBottom: '20px' }}>
            {this.state.error?.message || 'Неизвестная ошибка рендеринга'}
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '10px 20px',
              backgroundColor: '#4f46e5',
              color: '#ffffff',
              border: 'none',
              borderRadius: '6px',
              fontSize: '13px',
              cursor: 'pointer'
            }}
          >
            Обновить страницу
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function AppContent() {
  // Состояния агента и сессии
  const [status, setStatus] = useState({
    browser_running: false,
    is_busy: false,
    is_paused: false,
    is_ready: false
  });
  const [activeProvider, setActiveProvider] = useState(() => {
    try {
      return localStorage.getItem('mdagent_active_provider') || 'hydraai';
    } catch (_) {
      return 'hydraai';
    }
  });
  const [quotas, setQuotas] = useState(null);
  const [settingsData, setSettingsData] = useState(null);

  // Чат и логи
  const [messages, setMessages] = useState([]);
  const [logs, setLogs] = useState([]);

  // Трансляция экрана
  const [screenImage, setScreenImage] = useState(null);

  // Модальные окна
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [isStartingSession, setIsStartingSession] = useState(false);
  const isStartingRef = useRef(false);
  const startTimeoutRef = useRef(null);

  // Режим левой панели ('chat' | 'dialogs') и активная сессия
  const [viewMode, setViewMode] = useState('chat');
  const [activeSessionId, setActiveSessionId] = useState('default');
  const [activeSession, setActiveSession] = useState(null);

  // Регулировка ширины чата (Drag Resizing)
  const [chatWidth, setChatWidth] = useState(() => {
    try {
      const saved = localStorage.getItem('mdagent_chat_width');
      return saved ? parseInt(saved, 10) : 420;
    } catch (_) {
      return 420;
    }
  });
  const [isDragging, setIsDragging] = useState(false);

  const startResizing = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => {
      const minW = 280;
      const maxW = Math.max(minW, Math.min(window.innerWidth - 320, 850));
      const newW = Math.max(minW, Math.min(e.clientX, maxW));
      setChatWidth(newW);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      try {
        localStorage.setItem('mdagent_chat_width', chatWidth.toString());
      } catch (_) {}
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, chatWidth]);

  // WebSocket ссылка
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  // ─────────────────────────── Первоначальная загрузка через REST ───────────────────────────

  const loadInitialData = async () => {
    try {
      // 1. Сессии диалогов и активная сессия
      try {
        const sessRes = await fetch('/api/chat/sessions');
        if (sessRes.ok) {
          const sessData = await sessRes.json();
          if (sessData.active_session_id) setActiveSessionId(sessData.active_session_id);
          const cur = sessData.sessions?.find(s => s.id === sessData.active_session_id);
          if (cur) {
            setActiveSession(cur);
            if (cur.messages && Array.isArray(cur.messages)) {
              setMessages(cur.messages);
            }
          }
        }
      } catch (_) {}

      // 1.1. История чата (резерв)
      const chatRes = await fetch('/api/chat/history');
      if (chatRes.ok) {
        const chatData = await chatRes.json();
        if (chatData.messages && Array.isArray(chatData.messages)) {
          setMessages(chatData.messages);
        }
      }

      // 2. Статус агента
      const statusRes = await fetch('/api/status');
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setStatus(statusData);
        if (statusData.active_provider) {
          setActiveProvider(statusData.active_provider);
          try { localStorage.setItem('mdagent_active_provider', statusData.active_provider); } catch (_) {}
        }
      }

      // 3. Квоты
      const quotaRes = await fetch('/api/quota');
      if (quotaRes.ok) {
        const quotaData = await quotaRes.json();
        setQuotas(quotaData);
      }

      // 4. Настройки
      const settingsRes = await fetch('/api/settings');
      if (settingsRes.ok) {
        const setts = await settingsRes.json();
        setSettingsData(setts);
        if (setts.active_provider) {
          setActiveProvider(setts.active_provider);
          try { localStorage.setItem('mdagent_active_provider', setts.active_provider); } catch (_) {}
        }
      }
    } catch (e) {
      console.warn('Ошибка загрузки начальных данных:', e);
    }
  };

  // ─────────────────────────── WebSocket соединение ───────────────────────────

  const connectWebSocket = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    // Если запущено через Vite dev-server (порт 3000), используем порт 8000
    const wsHost = host.includes(':3000') ? '127.0.0.1:8000' : host;
    const wsUrl = `${protocol}//${wsHost}/ws`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      addLog('info', 'WebSocket подключён к серверу mdAgent');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleServerEvent(data);
      } catch (err) {
        console.error('Ошибка парсинга WS сообщения:', err);
      }
    };

    ws.onclose = () => {
      isStartingRef.current = false;
      setIsStartingSession(false);
      if (startTimeoutRef.current) clearTimeout(startTimeoutRef.current);
      addLog('warning', 'WebSocket соединение разорвано. Повторное подключение через 2с...');
      reconnectTimeoutRef.current = setTimeout(() => {
        connectWebSocket();
      }, 2000);
    };

    ws.onerror = (err) => {
      console.warn('WebSocket ошибка:', err);
      ws.close();
    };
  }, []);

  useEffect(() => {
    loadInitialData();
    connectWebSocket();

    // Периодическое обновление квот раз в 15 секунд
    const quotaInterval = setInterval(async () => {
      try {
        const res = await fetch('/api/quota');
        if (res.ok) setQuotas(await res.json());
      } catch (_) {}
    }, 15000);

    return () => {
      clearInterval(quotaInterval);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (startTimeoutRef.current) clearTimeout(startTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connectWebSocket]);

  // ─────────────────────────── Обработка событий сервера ───────────────────────────

  const handleServerEvent = (event) => {
    switch (event.type) {
      case 'chat_history':
        if (event.messages && Array.isArray(event.messages)) {
          setMessages(event.messages);
        }
        break;

      case 'session_switched':
        if (event.messages && Array.isArray(event.messages)) {
          setMessages(event.messages);
        }
        if (event.session_id) {
          setActiveSessionId(event.session_id);
        }
        if (event.session) {
          setActiveSession(event.session);
        }
        break;

      case 'chat_message':
        setMessages(prev => [...prev, event]);
        break;

      case 'chat_cleared':
        setMessages([]);
        addLog('info', 'История чата очищена');
        break;

      case 'status':
        setStatus(event);
        if (event.active_provider) setActiveProvider(event.active_provider);
        if (event.browser?.is_running || event.browser_running) {
          isStartingRef.current = false;
          setIsStartingSession(false);
          if (startTimeoutRef.current) clearTimeout(startTimeoutRef.current);
          sendWsAction('screenshot');
        }
        break;

      case 'log':
        addLog(event.level || 'info', event.message || '');
        break;

      case 'screencast_frame':
        if (event.image) {
          const src = event.image.startsWith('data:') ? event.image : `data:image/jpeg;base64,${event.image}`;
          setScreenImage(src);
        }
        break;

      case 'screenshot':
        if (event.image) {
          const src = event.image.startsWith('data:') ? event.image : `data:image/png;base64,${event.image}`;
          setScreenImage(src);
        }
        break;

      case 'error':
        isStartingRef.current = false;
        setIsStartingSession(false);
        if (startTimeoutRef.current) clearTimeout(startTimeoutRef.current);
        addLog('error', event.message || 'Произошла системная ошибка');
        break;

      default:
        break;
    }
  };

  const addLog = (level, message) => {
    const time = new Date().toLocaleTimeString();
    setLogs(prev => [...prev.slice(-300), { time, level, message }]);
  };

  // ─────────────────────────── Отправка команд на сервер ───────────────────────────

  const sendWsAction = (action, payload = {}) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action, ...payload }));
    } else {
      addLog('error', 'Нет активного соединения с сервером');
    }
  };

  const handleSendMessage = (text, imageBase64 = null) => {
    if (!text.trim() && !imageBase64) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'command',
        message: text,
        image: imageBase64 || ''
      }));
    }
  };

  const handleSelectSession = (sessionId) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'select_session',
        session_id: sessionId
      }));
    } else {
      fetch(`/api/chat/sessions/${sessionId}/select`, { method: 'POST' }).then(() => {
        loadInitialData();
      });
    }
    setActiveSessionId(sessionId);
    setViewMode('chat');
  };

  const handleStartSession = () => {
    if (isStartingRef.current || isStartingSession) {
      return;
    }
    isStartingRef.current = true;
    setIsStartingSession(true);

    // Предохранительный таймаут на 25 секунд
    if (startTimeoutRef.current) clearTimeout(startTimeoutRef.current);
    startTimeoutRef.current = setTimeout(() => {
      isStartingRef.current = false;
      setIsStartingSession(false);
    }, 25000);

    addLog('info', 'Запуск Chromium и инициализация сессии Tilda...');
    sendWsAction('start');
  };

  const handleStopSession = () => {
    addLog('info', 'Остановка сессии агента...');
    sendWsAction('stop');
  };

  const handlePause = () => {
    sendWsAction('pause');
  };

  const handleResume = () => {
    sendWsAction('resume');
  };

  const handleBringToFront = async () => {
    addLog('info', 'Окно Chromium выводится на передний план...');
    sendWsAction('bring_to_front');
  };

  const handleClearChatHistory = async () => {
    if (window.confirm('Очистить историю диалога?')) {
      sendWsAction('clear_chat');
      try {
        await fetch('/api/chat/history', { method: 'DELETE' });
      } catch (_) {}
    }
  };

  const handleBrowserInput = (inputData) => {
    sendWsAction('browser_input', inputData);
  };

  const handleRequestScreenshot = () => {
    sendWsAction('screenshot');
  };

  const handleConfirmPlan = (planId, steps) => {
    addLog('info', 'План утвержден. Запускаю выполнение...');
    sendWsAction('confirm_plan', { plan_id: planId, steps });
  };

  const handleCancelPlan = (planId) => {
    addLog('info', 'Выполнение плана отменено.');
    sendWsAction('cancel_plan', { plan_id: planId });
  };

  const handleSaveProvider = async (provider) => {
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider })
      });
      const data = await res.json();
      if (data.ok) {
        setActiveProvider(provider);
        try { localStorage.setItem('mdagent_active_provider', provider); } catch (_) {}
        addLog('success', `Активный AI изменен на: ${provider === 'hydraai' ? 'HydraAI (GPT-5.6 Luna)' : 'Google Gemini (Каскад)'}`);
      }
    } catch (e) {
      addLog('error', `Ошибка смены провайдера: ${e.message}`);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* Шапка */}
      <Header
        status={status}
        quotas={quotas}
        activeProvider={activeProvider}
        isStartingSession={isStartingSession}
        onStart={handleStartSession}
        onStop={handleStopSession}
        onPause={handlePause}
        onResume={handleResume}
        onBringToFront={handleBringToFront}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenMemory={() => setMemoryOpen(true)}
      />

      {/* Основная рабочая область (Split View с поддержкой Resize) */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Левая панель: Чат или Диалоги с динамической шириной */}
        <div style={{
          width: `${chatWidth}px`,
          minWidth: '280px',
          maxWidth: '850px',
          height: '100%',
          flexShrink: 0,
          position: 'relative'
        }}>
          {viewMode === 'dialogs' ? (
            <DialogsPanel
              activeSessionId={activeSessionId}
              onSelectSession={handleSelectSession}
              onBackToChat={() => setViewMode('chat')}
            />
          ) : (
            <ChatPanel
              messages={messages}
              isBusy={status.is_busy}
              onSendMessage={handleSendMessage}
              onClearHistory={handleClearChatHistory}
              onConfirmPlan={handleConfirmPlan}
              onCancelPlan={handleCancelPlan}
              onOpenDialogs={() => setViewMode('dialogs')}
              activeSessionTitle={activeSession?.title}
            />
          )}
        </div>

        {/* Разделитель с изменением ширины (Drag Splitter) */}
        <div
          className={`chat-resizer ${isDragging ? 'active' : ''}`}
          onMouseDown={startResizing}
          title="Потяните для изменения ширины панели чата"
        >
          <div className="chat-resizer-line" />
        </div>

        {/* Правая панель: Интерактивный вьюпорт трансляции (flex: 1) */}
        <div style={{ flex: 1, height: '100%', minWidth: '350px' }}>
          <LiveViewport
            screenImage={screenImage}
            isRunning={Boolean(status?.browser?.is_running || status?.browser_running)}
            isStartingSession={isStartingSession}
            currentUrl={status?.browser?.current_url}
            onStartSession={handleStartSession}
            onSendBrowserInput={handleBrowserInput}
            onRequestScreenshot={handleRequestScreenshot}
          />
        </div>
      </div>

      {/* Нижняя консоль логов */}
      <LogDrawer
        logs={logs}
        onClearLogs={() => setLogs([])}
      />

      {/* Модальные окна */}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        activeProvider={activeProvider}
        settingsData={settingsData}
        onSaveProvider={handleSaveProvider}
      />

      <MemoryModal
        isOpen={memoryOpen}
        onClose={() => setMemoryOpen(false)}
      />
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppContent />
    </ErrorBoundary>
  );
}
