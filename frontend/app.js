/**
 * mdAgent — Frontend Controller
 * Minimalist, luxury glassmorphism UI logic with WebSocket connection.
 */

// ═══════════════════════════════════════════════════════════════
//  State
// ═══════════════════════════════════════════════════════════════

let ws = null;
let isConnected = false;
let isBusy = false;

// DOM references
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const btnSend = document.getElementById('btnSend');
const btnStart = document.getElementById('btnStart');
const btnStop = document.getElementById('btnStop');
const btnPause = document.getElementById('btnPause');
const btnPauseText = document.getElementById('btnPauseText');
const btnPauseIcon = document.getElementById('btnPauseIcon');
const btnBringToFront = document.getElementById('btnBringToFront');
const interactiveBadge = document.getElementById('interactiveBadge');
const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const previewImage = document.getElementById('previewImage');
const previewPlaceholder = document.getElementById('previewPlaceholder');
const currentUrl = document.getElementById('currentUrl');
const logEntries = document.getElementById('logEntries');
const logPanel = document.getElementById('logPanel');
const memoryBadge = document.getElementById('memoryBadge');
const memoryModal = document.getElementById('memoryModal');
const playbooksList = document.getElementById('playbooksList');

let isAgentPaused = false;

// Gemini & AI Provider References
const quotaRpmVal = document.getElementById('quotaRpmVal');
const quotaRpdVal = document.getElementById('quotaRpdVal');
const quotaTimerVal = document.getElementById('quotaTimerVal');
const quotaTimerChip = document.getElementById('quotaTimerChip');
const quotaModelVal = document.getElementById('quotaModelVal');
const quotaModelChip = document.getElementById('quotaModelChip');

// Settings Modal references
const btnSettings = document.getElementById('btnSettings');
const settingsModal = document.getElementById('settingsModal');
const cardProviderGemini = document.getElementById('cardProviderGemini');
const cardProviderHydra = document.getElementById('cardProviderHydra');
const badgeGeminiActive = document.getElementById('badgeGeminiActive');
const badgeHydraActive = document.getElementById('badgeHydraActive');
const cascadeList = document.getElementById('cascadeList');
const hydraKeyMasked = document.getElementById('hydraKeyMasked');

let activeProvider = 'gemini';
let activeModel = 'gemini-3.8-flash';
let cascadeData = [];

let currentQuota = {
  rpm_limit: 15,
  rpm_remaining: 15,
  rpd_limit: 1500,
  rpd_remaining: 1500,
  reset_seconds: 0,
  day_reset_seconds: 0,
};
let quotaTickerInterval = null;


// ═══════════════════════════════════════════════════════════════
//  WebSocket Connection
// ═══════════════════════════════════════════════════════════════

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  addLogEntry('info', `Подключение к серверу: ${wsUrl}`);

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    isConnected = true;
    updateStatus('connected', 'Подключён');
    addLogEntry('success', 'WebSocket подключён');
  };

  ws.onclose = (event) => {
    isConnected = false;
    updateStatus('disconnected', 'Отключён');
    addLogEntry('warning', `WebSocket отключён (код: ${event.code})`);

    // Переподключение через 3 секунды
    setTimeout(() => {
      if (!isConnected) {
        addLogEntry('info', 'Повторное подключение...');
        connectWebSocket();
      }
    }, 3000);
  };

  ws.onerror = () => {
    addLogEntry('error', 'Ошибка сети WebSocket');
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerEvent(data);
    } catch (e) {
      console.error('Ошибка обработки сообщения:', e);
    }
  };
}

function handleServerEvent(data) {
  switch (data.type) {
    case 'log':
      addLogEntry(data.level || 'info', data.message || '');
      // Выводим важные системные сообщения и результаты в ленту чата
      if (
        data.level === 'error' ||
        data.level === 'success' ||
        data.message?.includes('успешно') ||
        data.message?.includes('Ошибка') ||
        data.message?.includes('подключен') ||
        data.message?.includes('найден') ||
        data.message?.includes('сохранен')
      ) {
        addAgentMessage(data.message);
      }
      break;


    case 'screencast_frame':
      if (data.image) {
        showScreencastFrame(data.image);
      }
      break;

    case 'screenshot':
      if (data.image) {
        showScreenshot(data.image);
      }
      break;

    case 'status':
      handleStatusUpdate(data);
      break;

    case 'memory_updated':
      if (data.playbooks) {
        renderPlaybooks(data.playbooks);
      }
      break;

    case 'error':
      addLogEntry('error', data.message || 'Системная ошибка');
      addAgentMessage(`Ошибка: ${data.message}`);
      break;

    default:
      console.log('Неизвестное событие:', data);
  }
}

function handleStatusUpdate(data) {
  const browser = data.browser || {};
  isBusy = data.is_busy || false;
  const isPaused = data.is_paused || false;
  isAgentPaused = isPaused;

  if (!isBusy) {
    removeTypingIndicator();
  }

  if (browser.is_running) {
    if (interactiveBadge) interactiveBadge.style.display = 'inline-flex';

    if (isBusy) {
      if (btnPause) btnPause.style.display = 'inline-flex';
      if (isPaused) {
        updateStatus('busy', 'Пауза (ручное управление)');
        if (btnPause) {
          btnPause.className = 'btn btn--success';
          btnPause.title = 'Возобновить выполнение плана агента';
        }
        if (btnPauseText) btnPauseText.textContent = 'Продолжить';
        if (btnPauseIcon) {
          btnPauseIcon.innerHTML = '<polygon points="6 3 20 12 6 21 6 3"></polygon>';
        }
      } else {
        updateStatus('busy', 'Выполняю команду...');
        if (btnPause) {
          btnPause.className = 'btn btn--warning';
          btnPause.title = 'Поставить работу агента на паузу для самостоятельных действий';
        }
        if (btnPauseText) btnPauseText.textContent = 'Пауза';
        if (btnPauseIcon) {
          btnPauseIcon.innerHTML = '<rect x="6" y="4" width="4" height="16" rx="1"></rect><rect x="14" y="4" width="4" height="16" rx="1"></rect>';
        }
      }
    } else {
      updateStatus('connected', browser.is_logged_in ? 'Tilda Активна' : 'Браузер готов');
      if (btnPause) btnPause.style.display = 'none';
    }

    if (btnStart) btnStart.disabled = true;
    if (btnStop) btnStop.disabled = false;

    // Если браузер работает, но превью еще не отображено — сразу запрашиваем кадр
    if (previewImage && previewImage.style.display !== 'block') {
      requestScreenshot();
    }
  } else {
    updateStatus('disconnected', 'Браузер выключен');
    if (btnStart) btnStart.disabled = false;
    if (btnStop) btnStop.disabled = true;
    if (btnPause) btnPause.style.display = 'none';
    if (interactiveBadge) interactiveBadge.style.display = 'none';
    if (previewImage && previewPlaceholder) {
      previewImage.style.display = 'none';
      previewPlaceholder.style.display = 'flex';
    }
  }

  if (browser.current_url && currentUrl) {
    currentUrl.textContent = browser.current_url;
  }

  if (data.playbooks_count !== undefined) {
    updateMemoryBadge(data.playbooks_count);
  }

  if (data.active_provider) {
    activeProvider = data.active_provider;
  }
  if (data.active_model) {
    activeModel = data.active_model;
  }
  if (data.gemini_cascade) {
    cascadeData = data.gemini_cascade;
    renderCascade(cascadeData);
  }
  updateModelChip();

  if (data.quota) {
    updateQuotaDisplay(data.quota);
  }
}


// ═══════════════════════════════════════════════════════════════
//  Actions
// ═══════════════════════════════════════════════════════════════

async function startAgent() {
  if (!isConnected) {
    connectWebSocket();
    await new Promise((resolve) => {
      const check = setInterval(() => {
        if (isConnected) {
          clearInterval(check);
          resolve();
        }
      }, 100);
      setTimeout(() => { clearInterval(check); resolve(); }, 5000);
    });
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'start' }));
    addLogEntry('info', 'Запуск браузера и инициализация сессии...');
    if (btnStart) btnStart.disabled = true;
  }
}

async function stopAgent() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'stop' }));
    addLogEntry('info', 'Запрос на остановку браузера...');
    if (btnStop) btnStop.disabled = true;
    if (btnPause) btnPause.style.display = 'none';
    isAgentPaused = false;
  }
}

function togglePauseAgent() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (!isAgentPaused) {
    ws.send(JSON.stringify({ action: 'pause' }));
    isAgentPaused = true;
    if (btnPause) {
      btnPause.className = 'btn btn--success';
      btnPause.title = 'Возобновить выполнение плана агента';
    }
    if (btnPauseText) btnPauseText.textContent = 'Продолжить';
    if (btnPauseIcon) {
      btnPauseIcon.innerHTML = '<polygon points="6 3 20 12 6 21 6 3"></polygon>';
    }
    updateStatus('busy', 'Пауза (ручное управление)');
  } else {
    ws.send(JSON.stringify({ action: 'resume' }));
    isAgentPaused = false;
    if (btnPause) {
      btnPause.className = 'btn btn--warning';
      btnPause.title = 'Поставить работу агента на паузу для самостоятельных действий';
    }
    if (btnPauseText) btnPauseText.textContent = 'Пауза';
    if (btnPauseIcon) {
      btnPauseIcon.innerHTML = '<rect x="6" y="4" width="4" height="16" rx="1"></rect><rect x="14" y="4" width="4" height="16" rx="1"></rect>';
    }
    updateStatus('busy', 'Выполняю команду...');
  }
}

function bringBrowserToFront() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'bring_to_front' }));
    addLogEntry('info', 'Запрос на вывод окна Chromium на передний план...');
  }
}

function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  if (!isConnected) {
    addLogEntry('error', 'Нет активного соединения с сервером');
    return;
  }

  addUserMessage(text);

  ws.send(JSON.stringify({
    action: 'command',
    message: text,
  }));

  chatInput.value = '';
  autoResize(chatInput);
  showTypingIndicator();
}

function sendQuickAction(text) {
  chatInput.value = text;
  sendMessage();
}

function requestScreenshot() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'screenshot' }));
  }
}

// ═══════════════════════════════════════════════════════════════
//  UI Updaters
// ═══════════════════════════════════════════════════════════════

function updateStatus(state, text) {
  if (statusIndicator) {
    statusIndicator.className = `status-indicator status-indicator--${state}`;
  }
  if (statusText) {
    statusText.textContent = text;
  }
}

function showScreenshot(base64) {
  if (previewImage && previewPlaceholder) {
    previewImage.src = `data:image/png;base64,${base64}`;
    previewImage.style.display = 'block';
    previewPlaceholder.style.display = 'none';
  }
}

function showScreencastFrame(base64) {
  if (previewImage && previewPlaceholder) {
    previewImage.src = `data:image/jpeg;base64,${base64}`;
    if (previewImage.style.display !== 'block') {
      previewImage.style.display = 'block';
      previewPlaceholder.style.display = 'none';
    }
  }
}

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatMessageContent(text) {
  if (!text) return '';
  const escaped = escapeHtml(text);
  // Превращаем URL в кликабельные интерактивные ссылки
  return escaped.replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer" style="color: #60a5fa; text-decoration: underline; font-weight: 500; word-break: break-all;">$1</a>'
  );
}

function addUserMessage(text) {
  clearEmptyState();
  removeTypingIndicator();

  const div = document.createElement('div');
  div.className = 'message message--user';
  div.innerHTML = `
    <div class="message__avatar">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
        <circle cx="12" cy="7" r="4"></circle>
      </svg>
    </div>
    <div class="message__bubble">${formatMessageContent(text)}</div>
  `;
  chatMessages.appendChild(div);
  scrollChat();
}

function addAgentMessage(text) {
  removeTypingIndicator();
  clearEmptyState();

  const div = document.createElement('div');
  div.className = 'message message--agent';
  div.innerHTML = `
    <div class="message__avatar">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
        <polyline points="2 17 12 22 22 17"></polyline>
        <polyline points="2 12 12 17 22 12"></polyline>
      </svg>
    </div>
    <div class="message__bubble">${formatMessageContent(text)}</div>
  `;
  chatMessages.appendChild(div);
  scrollChat();
}

function showTypingIndicator() {
  removeTypingIndicator();

  const div = document.createElement('div');
  div.className = 'message message--agent';
  div.id = 'typingIndicator';
  div.innerHTML = `
    <div class="message__avatar">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
        <polyline points="2 17 12 22 22 17"></polyline>
        <polyline points="2 12 12 17 22 12"></polyline>
      </svg>
    </div>
    <div class="message__bubble">
      <div class="typing-indicator">
        <span class="typing-indicator__dot"></span>
        <span class="typing-indicator__dot"></span>
        <span class="typing-indicator__dot"></span>
      </div>
    </div>
  `;
  chatMessages.appendChild(div);
  scrollChat();
}

function removeTypingIndicator() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

function addLogEntry(level, message) {
  const time = new Date().toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  let logLevel = level;
  if (
    message.includes('успешно') ||
    message.includes('сохранена') ||
    message.includes('опубликована') ||
    message.includes('Авторизация успешна')
  ) {
    logLevel = 'success';
  }

  const div = document.createElement('div');
  div.className = `log-entry log-entry--${logLevel}`;
  div.innerHTML = `
    <span class="log-entry__time">${time}</span>
    <span class="log-entry__text">${escapeHtml(message)}</span>
  `;
  if (logEntries) {
    logEntries.appendChild(div);
  }

  if (logPanel) {
    logPanel.scrollTop = logPanel.scrollHeight;
  }

  if (logEntries) {
    while (logEntries.children.length > 200) {
      logEntries.removeChild(logEntries.firstChild);
    }
  }
}

function clearChat() {
  if (chatMessages) {
    chatMessages.innerHTML = `
      <div class="chat__empty">
        <div class="chat__empty-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 20h9"></path>
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
          </svg>
        </div>
        <div class="chat__empty-text">
          История команд очищена. Отправьте новое указание для агента.
        </div>
      </div>
    `;
  }
}

function clearEmptyState() {
  const empty = chatMessages?.querySelector('.chat__empty');
  if (empty) empty.remove();
}

function clearLog() {
  if (logEntries) {
    logEntries.innerHTML = '';
  }
  addLogEntry('info', 'Журнал очищен');
}

async function copyLog() {
  const entries = document.querySelectorAll('.log-entry');
  if (!entries || entries.length === 0) {
    addLogEntry('warning', 'Журнал пуст, нечего копировать');
    return;
  }

  const lines = [];
  entries.forEach((el) => {
    const time = el.querySelector('.log-entry__time')?.innerText?.trim() || '';
    const text = el.querySelector('.log-entry__text')?.innerText?.trim() || '';
    if (time && text) {
      lines.push(`[${time}] ${text}`);
    } else if (text) {
      lines.push(text);
    }
  });

  const fullText = lines.join('\n');
  const btn = document.getElementById('btnCopyLog');

  try {
    await navigator.clipboard.writeText(fullText);
  } catch (err) {
    // Fallback
    const ta = document.createElement('textarea');
    ta.value = fullText;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }

  if (btn) {
    btn.classList.add('copied');
    const oldHtml = btn.innerHTML;
    btn.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"></polyline>
      </svg>
    `;
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = oldHtml;
    }, 2000);
  }
  addLogEntry('info', `Скопировано в буфер обмена: ${lines.length} записей`);
}

function scrollChat() {
  if (chatMessages) {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }
}

// ═══════════════════════════════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════════════════════════════

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function handleInputKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}

function autoResize(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

// ═══════════════════════════════════════════════════════════════
//  Memory & Skills
// ═══════════════════════════════════════════════════════════════

let cachedPlaybooks = [];

async function loadMemory() {
  try {
    const res = await fetch('/api/memory');
    if (res.ok) {
      const data = await res.json();
      cachedPlaybooks = data.playbooks || [];
      renderPlaybooks(cachedPlaybooks);
    }
  } catch (e) {
    console.error('Ошибка загрузки памяти playbooks:', e);
  }
}

function updateMemoryBadge(count) {
  if (memoryBadge) {
    memoryBadge.textContent = count;
  }
}

function renderPlaybooks(playbooks) {
  cachedPlaybooks = playbooks || [];
  updateMemoryBadge(cachedPlaybooks.length);

  if (!playbooksList) return;

  if (cachedPlaybooks.length === 0) {
    playbooksList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;">Пока нет сохраненных навыков</div>';
    return;
  }

  playbooksList.innerHTML = cachedPlaybooks.map((p) => {
    const tagClass = p.is_builtin ? 'playbook-card__tag--builtin' : 'playbook-card__tag--learned';
    const tagText = p.is_builtin ? 'Базовый' : 'Изучен AI';
    const successRate = (p.success_count || 0) > 0 ? `<span class="playbook-card__success">Успехов: ${p.success_count}</span>` : '';

    const stepsHtml = (p.actions || []).map((a, idx) => `
      <span class="playbook-step" title="${escapeHtml(a.description || a.action)}">
        ${idx + 1}. ${escapeHtml(a.action)}
      </span>
    `).join('');

    return `
      <div class="playbook-card">
        <div class="playbook-card__top">
          <div class="playbook-card__info">
            <div class="playbook-card__icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                <polyline points="2 17 12 22 22 17"></polyline>
                <polyline points="2 12 12 17 22 12"></polyline>
              </svg>
            </div>
            <div class="playbook-card__text">
              <div class="playbook-card__name">${escapeHtml(p.name)}</div>
              <div class="playbook-card__desc">${escapeHtml(p.description || '')}</div>
            </div>
          </div>
          <div class="playbook-card__meta">
            <span class="playbook-card__tag ${tagClass}">${tagText}</span>
            ${successRate}
          </div>
        </div>
        <div class="playbook-card__actions">${stepsHtml}</div>
      </div>
    `;
  }).join('');
}

function openMemoryModal() {
  if (memoryModal) {
    loadMemory();
    memoryModal.classList.add('open');
  }
}

function closeMemoryModal(event) {
  if (!event || event.target === memoryModal || event.currentTarget?.classList.contains('btn--icon')) {
    if (memoryModal) {
      memoryModal.classList.remove('open');
    }
  }
}

// ═══════════════════════════════════════════════════════════════
//  Settings & AI Provider Management
// ═══════════════════════════════════════════════════════════════

function openSettingsModal() {
  if (settingsModal) {
    loadSettings();
    settingsModal.classList.add('open');
  }
}

function closeSettingsModal(event) {
  if (!event || event.target === settingsModal || event.currentTarget?.classList.contains('btn--icon')) {
    if (settingsModal) {
      settingsModal.classList.remove('open');
    }
  }
}

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    if (res.ok) {
      const data = await res.json();
      applySettingsData(data);
    }
  } catch (e) {
    console.error('Ошибка загрузки настроек:', e);
  }
}

function applySettingsData(data) {
  if (!data) return;
  activeProvider = data.active_provider || 'gemini';

  const geminiProv = data.providers?.find((p) => p.id === 'gemini');
  const hydraProv = data.providers?.find((p) => p.id === 'hydraai');

  if (geminiProv && geminiProv.cascade) {
    cascadeData = geminiProv.cascade;
    renderCascade(cascadeData);
  }

  // Обновляем радио-карточки провайдеров
  if (cardProviderGemini && cardProviderHydra) {
    if (activeProvider === 'gemini') {
      cardProviderGemini.classList.add('active');
      cardProviderHydra.classList.remove('active');
      if (badgeGeminiActive) {
        badgeGeminiActive.className = 'provider-card__badge provider-card__badge--active';
        badgeGeminiActive.textContent = 'Активен';
      }
      if (badgeHydraActive) {
        badgeHydraActive.className = 'provider-card__badge';
        badgeHydraActive.textContent = 'Резерв';
      }
    } else {
      cardProviderHydra.classList.add('active');
      cardProviderGemini.classList.remove('active');
      if (badgeHydraActive) {
        badgeHydraActive.className = 'provider-card__badge provider-card__badge--active';
        badgeHydraActive.textContent = 'Активен';
      }
      if (badgeGeminiActive) {
        badgeGeminiActive.className = 'provider-card__badge';
        badgeGeminiActive.textContent = 'Резерв';
      }
    }
  }

  updateModelChip();
}

function renderCascade(ladder) {
  if (!cascadeList || !ladder) return;
  cascadeList.innerHTML = ladder.map((item, idx) => {
    const isActive = item.is_active;
    const isFloor = item.priority.includes('3.0') || item.priority.includes('Базовый');
    const activeClass = isActive ? 'cascade-item--active' : '';
    const floorClass = isFloor ? 'cascade-item--floor' : '';
    const statusText = isActive ? 'Активна' : 'Резерв';
    const statusPillClass = isActive ? 'cascade-item__status-pill--active' : 'cascade-item__status-pill--standby';
    const tagText = idx === 0 ? 'Основная' : (isFloor ? 'Порог 3.0' : 'Резерв');

    return `
      <div class="cascade-item ${activeClass} ${floorClass}">
        <div class="cascade-item__left">
          <span class="cascade-item__dot"></span>
          <span class="cascade-item__name">${item.name}</span>
          <span class="cascade-item__priority-tag">${tagText}</span>
        </div>
        <div class="cascade-item__right">
          <div class="cascade-item__stat" title="Доступно запросов в минуту">
            <span>${item.rpm_remaining}</span>/${item.rpm_limit} RPM
          </div>
          <div class="cascade-item__status-pill ${statusPillClass}">
            <span class="cascade-item__status-dot"></span>
            <span>${statusText}</span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}


async function selectProvider(provider) {
  if (provider === activeProvider) return;
  try {
    const provTitle = provider === 'hydraai' ? 'HydraAI (GPT-5.6 Luna)' : 'Google Gemini (Каскад)';
    addLogEntry('info', `Переключение на AI: ${provTitle}...`);
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.ok) {
        await loadSettings();
        await loadQuota();
      }
    }
  } catch (e) {
    console.error('Ошибка переключения провайдера:', e);
    addLogEntry('error', `Не удалось переключить AI провайдера: ${e.message}`);
  }
}

function updateModelChip() {
  if (!quotaModelVal) return;
  if (activeProvider === 'hydraai') {
    quotaModelVal.textContent = 'Luna 5.6';
    if (quotaModelChip) quotaModelChip.title = 'HydraAI (GPT-5.6 Luna) — активна (87 TPS, 256k)';
  } else {
    const activeCascadeItem = cascadeData.find((c) => c.is_active);
    const name = activeCascadeItem ? activeCascadeItem.name : '3.8 Flash';
    quotaModelVal.textContent = name.replace(' Preview', '');
    if (quotaModelChip) quotaModelChip.title = `Google Gemini — активна модель ${name} (каскад до 3.0)`;
  }
}

// ═══════════════════════════════════════════════════════════════
//  Gemini API Quota Tracking
// ═══════════════════════════════════════════════════════════════

async function loadQuota() {
  try {
    const res = await fetch('/api/quota');
    if (res.ok) {
      const data = await res.json();
      updateQuotaDisplay(data);
    }
  } catch (e) {
    console.error('Ошибка загрузки данных квоты:', e);
  }
}

function updateQuotaDisplay(quota) {
  if (!quota) return;
  currentQuota = { ...currentQuota, ...quota };

  if (quota.cascade) {
    cascadeData = quota.cascade;
    renderCascade(cascadeData);
  }

  if (quotaRpmVal) {
    quotaRpmVal.textContent = `${currentQuota.rpm_remaining}/${currentQuota.rpm_limit}`;
  }
  if (quotaRpdVal) {
    quotaRpdVal.textContent = `${currentQuota.rpd_remaining}/${currentQuota.rpd_limit}`;
  }
  if (quotaTimerVal) {
    if (currentQuota.reset_seconds > 0) {
      quotaTimerVal.textContent = `${currentQuota.reset_seconds}с`;
    } else {
      quotaTimerVal.textContent = '60с';
    }
  }
  if (quotaTimerChip) {
    if (currentQuota.rpm_remaining <= 2) {
      quotaTimerChip.classList.add('api-limits__chip--low');
    } else {
      quotaTimerChip.classList.remove('api-limits__chip--low');
    }
  }
}

function startQuotaTicker() {
  if (quotaTickerInterval) clearInterval(quotaTickerInterval);
  quotaTickerInterval = setInterval(() => {
    if (currentQuota.reset_seconds > 0) {
      currentQuota.reset_seconds--;
      if (quotaTimerVal) {
        quotaTimerVal.textContent = `${currentQuota.reset_seconds}с`;
      }
    } else if (currentQuota.rpm_remaining < currentQuota.rpm_limit) {
      currentQuota.rpm_remaining++;
      currentQuota.reset_seconds = 60;
      updateQuotaDisplay(currentQuota);
    }
  }, 1000);
}

// ═══════════════════════════════════════════════════════════════
//  Interactive Remote Browser Control (CDP Remote Input)
// ═══════════════════════════════════════════════════════════════

function setupInteractiveViewport() {
  if (!previewImage) return;

  function getBrowserCoords(e) {
    const rect = previewImage.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const scaleX = 1920 / rect.width;
    const scaleY = 1080 / rect.height;
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);
    return {
      x: Math.max(0, Math.min(1920, x)),
      y: Math.max(0, Math.min(1080, y))
    };
  }

  // Клик левой кнопкой мыши по браузеру
  previewImage.addEventListener('click', (e) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const coords = getBrowserCoords(e);
    if (!coords) return;
    previewImage.focus();
    ws.send(JSON.stringify({
      action: 'browser_input',
      event: 'click',
      x: coords.x,
      y: coords.y,
      button: 'left'
    }));
  });

  // Клик правой кнопкой мыши (контекстное меню в браузере)
  previewImage.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const coords = getBrowserCoords(e);
    if (!coords) return;
    previewImage.focus();
    ws.send(JSON.stringify({
      action: 'browser_input',
      event: 'click',
      x: coords.x,
      y: coords.y,
      button: 'right'
    }));
  });

  // Скролл колесиком мыши
  previewImage.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const coords = getBrowserCoords(e);
    ws.send(JSON.stringify({
      action: 'browser_input',
      event: 'wheel',
      deltaX: e.deltaX,
      deltaY: e.deltaY,
      x: coords ? coords.x : 960,
      y: coords ? coords.y : 540
    }));
  }, { passive: false });

  // Ввод с клавиатуры при фокусе на превью
  previewImage.addEventListener('keydown', (e) => {
    // Не перехватываем системные клавиши F5, F12 и т.д.
    if (['F5', 'F11', 'F12'].includes(e.key)) return;
    if (e.ctrlKey && ['r', 'R'].includes(e.key)) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    e.preventDefault();

    ws.send(JSON.stringify({
      action: 'browser_input',
      event: 'keydown',
      key: e.key,
      text: (e.key.length === 1 && !e.ctrlKey && !e.altKey) ? e.key : '',
      ctrlKey: e.ctrlKey,
      altKey: e.altKey,
      shiftKey: e.shiftKey
    }));
  });
}

// ═══════════════════════════════════════════════════════════════
//  Initialization
// ═══════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  addLogEntry('info', 'mdAgent UI инициализирован');
  connectWebSocket();
  setupInteractiveViewport();
  loadMemory();
  loadSettings();
  loadQuota();
  startQuotaTicker();
});

