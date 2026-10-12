import React, { useState, useRef } from 'react';
import { 
  Maximize2, 
  Minimize2, 
  Monitor, 
  Camera, 
  Play, 
  Square,
  RotateCw, 
  Globe,
  KeyRound,
  Layers,
  Code,
  ShieldCheck,
  Loader2
} from 'lucide-react';

export default function LiveViewport({
  screenImage,
  isRunning,
  isStartingSession,
  currentUrl,
  onStartSession,
  onStopSession,
  onSendBrowserInput,
  onRequestScreenshot,
  onOpenTildaModal,
  onSelectPrompt
}) {
  const [interactiveMode, setInteractiveMode] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [orbTilt, setOrbTilt] = useState({ x: 0, y: 0 });
  const [orbPulse, setOrbPulse] = useState(false);
  const orbRef = useRef(null);
  const containerRef = useRef(null);
  const imgRef = useRef(null);
  const wheelAccumulatorRef = useRef({ deltaX: 0, deltaY: 0, x: 960, y: 540 });
  const wheelRafRef = useRef(null);
  const isDraggingRef = useRef(false);

  const handleOrbMouseMove = (e) => {
    if (!orbRef.current) return;
    const rect = orbRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const dx = (e.clientX - centerX) / (rect.width / 2);
    const dy = (e.clientY - centerY) / (rect.height / 2);
    setOrbTilt({
      x: Math.max(-1, Math.min(1, dx)) * 14,
      y: Math.max(-1, Math.min(1, dy)) * -14
    });
  };

  const handleOrbMouseLeave = () => {
    setOrbTilt({ x: 0, y: 0 });
  };

  const handleOrbClick = () => {
    setOrbPulse(true);
    setTimeout(() => setOrbPulse(false), 500);
  };

  // Вычисление точных координат курсора (1920x1080)
  const getNormalizedCoords = (e) => {
    if (!imgRef.current) return { x: 960, y: 540 };
    const rect = imgRef.current.getBoundingClientRect();
    const clientX = e.clientX - rect.left;
    const clientY = e.clientY - rect.top;

    const x = Math.round(clientX * (1920 / rect.width));
    const y = Math.round(clientY * (1080 / rect.height));

    return {
      x: Math.max(0, Math.min(1920, x)),
      y: Math.max(0, Math.min(1080, y))
    };
  };

  const handleImageClick = (e) => {
    if (!interactiveMode || !isRunning || !imgRef.current) return;
    const { x, y } = getNormalizedCoords(e);
    const button = e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left';
    onSendBrowserInput({ event: 'click', x, y, button });
  };

  const handleWheel = (e) => {
    if (!isRunning) return;
    e.preventDefault();
    e.stopPropagation();

    const { x, y } = getNormalizedCoords(e);
    wheelAccumulatorRef.current.deltaX += e.deltaX;
    wheelAccumulatorRef.current.deltaY += e.deltaY;
    wheelAccumulatorRef.current.x = x;
    wheelAccumulatorRef.current.y = y;

    if (!wheelRafRef.current) {
      wheelRafRef.current = setTimeout(() => {
        const dx = Math.round(wheelAccumulatorRef.current.deltaX);
        const dy = Math.round(wheelAccumulatorRef.current.deltaY);
        const curX = wheelAccumulatorRef.current.x;
        const curY = wheelAccumulatorRef.current.y;

        wheelAccumulatorRef.current = { deltaX: 0, deltaY: 0, x: curX, y: curY };
        wheelRafRef.current = null;

        if (dx !== 0 || dy !== 0) {
          onSendBrowserInput({ event: 'wheel', x: curX, y: curY, deltaX: dx, deltaY: dy });
        }
      }, 30);
    }
  };

  const handleMouseDown = (e) => {
    if (!interactiveMode || !isRunning) return;
    isDraggingRef.current = true;
    const { x, y } = getNormalizedCoords(e);
    onSendBrowserInput({ event: 'mousedown', x, y, button: 'left' });
  };

  const handleMouseMove = (e) => {
    if (!interactiveMode || !isRunning || !isDraggingRef.current) return;
    const { x, y } = getNormalizedCoords(e);
    onSendBrowserInput({ event: 'mousemove', x, y });
  };

  const handleMouseUp = (e) => {
    if (!interactiveMode || !isRunning) return;
    isDraggingRef.current = false;
    const { x, y } = getNormalizedCoords(e);
    onSendBrowserInput({ event: 'mouseup', x, y, button: 'left' });
  };

  const handleManualRefresh = () => {
    setIsRefreshing(true);
    onRequestScreenshot?.();
    setTimeout(() => setIsRefreshing(false), 800);
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!isFullscreen) {
      if (containerRef.current.requestFullscreen) {
        containerRef.current.requestFullscreen();
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    }
    setIsFullscreen(!isFullscreen);
  };

  const hasStream = Boolean(isRunning || screenImage);

  return (
    <div 
      ref={containerRef} 
      className="figma-main-card"
      style={{ height: '100%' }}
    >
      {/* ────────────────── ФИКСИРОВАННАЯ ШАПКА СКРИНКАСТА ────────────────── */}
      <div className="screencast-top-bar">
        <div className="screencast-left-actions">
          {/* Кнопка 1: Аккаунт Tilda */}
          <button
            type="button"
            className="screencast-tilda-btn"
            onClick={onOpenTildaModal}
            title="Ввести логин и пароль от Tilda"
          >
            <KeyRound size={15} color="#7C3AED" />
            <span>Аккаунт Tilda</span>
          </button>

          {/* Кнопка 2: Окно браузера */}
          <button
            type="button"
            className={`screencast-window-btn ${isRunning ? 'active' : ''}`}
            title={isRunning ? 'Браузер Chromium активен' : 'Браузер ожидает запуска'}
          >
            <Monitor size={15} />
            <span>Окно браузера</span>
            <span className={`screencast-status-badge ${isRunning ? 'live' : 'idle'}`}>
              {isStartingSession ? 'Запуск...' : isRunning ? 'Live' : 'Готов'}
            </span>
          </button>

          {/* URL текущей страницы */}
          {currentUrl && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '11px',
              color: '#6B7280',
              background: '#F9FAFB',
              padding: '4px 10px',
              borderRadius: '8px',
              maxWidth: '320px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}>
              <Globe size={13} color="#9CA3AF" />
              <span>{currentUrl}</span>
            </div>
          )}
        </div>

        {/* Действия справа */}
        <div className="screencast-right-actions">
          {isRunning && (
            <>
              <button
                type="button"
                className="screencast-icon-btn"
                onClick={handleManualRefresh}
                title="Обновить кадр"
              >
                <RotateCw size={14} className={isRefreshing ? 'spin' : ''} />
              </button>
              <button
                type="button"
                className="screencast-icon-btn"
                onClick={onRequestScreenshot}
                title="Сделать снимок экрана"
              >
                <Camera size={14} />
              </button>
            </>
          )}

          {/* Старт / Стоп браузера */}
          {!isRunning ? (
            <button
              type="button"
              className="screencast-start-btn"
              onClick={onStartSession}
              disabled={isStartingSession}
            >
              {isStartingSession ? (
                <>
                  <Loader2 size={13} className="spin" />
                  <span>Запуск...</span>
                </>
              ) : (
                <>
                  <Play size={13} fill="#fff" />
                  <span>Запустить Chromium</span>
                </>
              )}
            </button>
          ) : (
            <button
              type="button"
              className="screencast-tilda-btn"
              onClick={onStopSession}
              style={{ color: '#EF4444', borderColor: '#FCA5A5' }}
            >
              <Square size={13} fill="#EF4444" />
              <span>Остановить</span>
            </button>
          )}

          <button
            type="button"
            className="screencast-icon-btn"
            onClick={toggleFullscreen}
            title={isFullscreen ? 'Выйти из полноэкранного режима' : 'На весь экран'}
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* ────────────────── ОСНОВНОЙ КОНТЕНТ ────────────────── */}
      {hasStream ? (
        /* РЕЖИМ АКТИВНОЙ ТРАНСЛЯЦИИ CHROMIUM */
        <div 
          className="figma-screencast-stream-area"
          onWheel={handleWheel}
        >
          {screenImage ? (
            <div className="stream-screen-container">
              <div className="stream-screen-box">
                <img
                  ref={imgRef}
                  src={screenImage}
                  alt="mdAgent Screen"
                  onClick={handleImageClick}
                  onMouseDown={handleMouseDown}
                  onMouseMove={handleMouseMove}
                  onMouseUp={handleMouseUp}
                  onDragStart={(e) => e.preventDefault()}
                  style={{
                    cursor: interactiveMode ? 'pointer' : 'default',
                  }}
                />
              </div>
            </div>
          ) : (
            <div style={{ color: '#9CA3AF', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
              <Loader2 size={28} className="spin" color="#8B5CF6" />
              <div style={{ fontSize: '13px' }}>Подключение к видеотрансляции Chromium...</div>
            </div>
          )}
        </div>
      ) : (
        /* РЕЖИМ ПОКОЯ (FIGMA WELCOME VIEW: 3D ORB & 3 FEATURES) */
        <div className="figma-welcome-view">
          {/* Интерактивная живая 3D-сфера со свечением и тенью */}
          <div 
            ref={orbRef}
            className="orb-stage"
            onMouseMove={handleOrbMouseMove}
            onMouseLeave={handleOrbMouseLeave}
            onClick={handleOrbClick}
            title="Интеллектуальное ядро mdAgent (кликните для светового импульса)"
          >
            {/* Ореол свечения (Aura Bloom) */}
            <div className="orb-aura-glow" />

            {/* Орбитальное световое кольцо энергии */}
            <div className="orb-energy-ring" />

            {/* Живая сфера с 3D-наклоном и динамическим смещением блика */}
            <div 
              className="purple-orb-3d"
              style={{
                transform: `perspective(600px) rotateX(${orbTilt.y}deg) rotateY(${orbTilt.x}deg) scale(${orbPulse ? 1.12 : 1})`,
                background: `radial-gradient(circle at ${32 + orbTilt.x * 0.5}% ${28 - orbTilt.y * 0.5}%, #FFFFFF 0%, #E9D5FF 28%, #A855F7 62%, #6D28D9 86%, #4C1D95 100%)`
              }}
            />

            {/* Контактная тень под сферой */}
            <div className="orb-contact-shadow" />
          </div>

          {/* Приветствие */}
          <div className="welcome-greeting-title">
            mdAgent
          </div>
          <div className="welcome-greeting-heading">
            Интеллектуальная автоматизация сайтов на Tilda
          </div>

          {/* 3 карточки возможностей */}
          <div className="welcome-cards-grid">
            {/* Карточка 1 */}
            <div 
              className="welcome-feature-card"
              onClick={() => onSelectPrompt?.('Зайди на страницу карточка товара, настрой стили под минимализм')}
            >
              <div className="welcome-card-icon-box">
                <Layers size={20} />
              </div>
              <div className="welcome-card-title">
                Автоматизация в админке
              </div>
              <div className="welcome-card-desc">
                Навигация по проектам, поиск страниц, добавление блоков из каталога и редактирование параметров по текстовым командам.
              </div>
            </div>

            {/* Карточка 2 */}
            <div 
              className="welcome-feature-card"
              onClick={() => onSelectPrompt?.('Стилизуй карточку товара под гласоморфизм, замени выпадающие селекты вариантов на кликабельные кнопки')}
            >
              <div className="welcome-card-icon-box">
                <Code size={20} />
              </div>
              <div className="welcome-card-title">
                Кастомизация и код T123
              </div>
              <div className="welcome-card-desc">
                Стилизация карточек под минимализм и гласоморфизм, замена селектов на кнопки, генерация адаптивного CSS и JS.
              </div>
            </div>

            {/* Карточка 3 */}
            <div 
              className="welcome-feature-card"
              onClick={() => onSelectPrompt?.('Создай стандартный блок попап формы BF502 и проверь работу на опубликованном сайте')}
            >
              <div className="welcome-card-icon-box">
                <ShieldCheck size={20} />
              </div>
              <div className="welcome-card-title">
                Closed-Loop верификация
              </div>
              <div className="welcome-card-desc">
                Автономная проверка боевого сайта на второй вкладке, валидация верстки в DOM и устранение ошибок без ложных рапортов.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
