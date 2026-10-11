import React, { useState, useRef } from 'react';
import { 
  Maximize2, 
  Minimize2, 
  MousePointer, 
  Monitor, 
  Camera, 
  Play, 
  RotateCw, 
  Globe,
  Loader2
} from 'lucide-react';

export default function LiveViewport({
  screenImage,
  isRunning,
  isStartingSession,
  currentUrl,
  onStartSession,
  onSendBrowserInput,
  onRequestScreenshot
}) {
  // Интерактивный режим ВКЛЮЧЕН по умолчанию для мгновенного управления
  const [interactiveMode, setInteractiveMode] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const containerRef = useRef(null);
  const imgRef = useRef(null);
  const wheelAccumulatorRef = useRef({ deltaX: 0, deltaY: 0, x: 960, y: 540 });
  const wheelRafRef = useRef(null);
  const isDraggingRef = useRef(false);

  // Вычисление точных координат курсора, нормализованных под Viewport Chromium 1920x1080
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

  // Обработка клика по трансляции
  const handleImageClick = (e) => {
    if (!interactiveMode || !isRunning || !imgRef.current) return;

    const { x, y } = getNormalizedCoords(e);
    const button = e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left';

    onSendBrowserInput({
      event: 'click',
      x,
      y,
      button
    });
  };

  // Обработка скролла колесом мыши с троттлингом и накоплением смещения (батчинг)
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
          onSendBrowserInput({
            event: 'wheel',
            x: curX,
            y: curY,
            deltaX: dx,
            deltaY: dy
          });
        }
      }, 30);
    }
  };

  // Поддержка перетаскивания (драга ползунка скроллбара и выделения)
  const handleMouseDown = (e) => {
    if (!interactiveMode || !isRunning) return;
    isDraggingRef.current = true;
    const { x, y } = getNormalizedCoords(e);
    const button = e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left';
    onSendBrowserInput({
      event: 'mousedown',
      x,
      y,
      button
    });
  };

  const handleMouseMove = (e) => {
    if (!interactiveMode || !isRunning || !isDraggingRef.current) return;
    const { x, y } = getNormalizedCoords(e);
    onSendBrowserInput({
      event: 'mousemove',
      x,
      y
    });
  };

  const handleMouseUp = (e) => {
    if (!interactiveMode || !isRunning) return;
    if (isDraggingRef.current) {
      isDraggingRef.current = false;
      const { x, y } = getNormalizedCoords(e);
      const button = e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left';
      onSendBrowserInput({
        event: 'mouseup',
        x,
        y,
        button
      });
    }
  };

  const handleManualRefresh = () => {
    setIsRefreshing(true);
    onRequestScreenshot();
    setTimeout(() => setIsRefreshing(false), 600);
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen?.();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.();
      setIsFullscreen(false);
    }
  };

  return (
    <div 
      ref={containerRef}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--bg-base)',
        position: 'relative',
        overflow: 'hidden'
      }}
    >
      {/* Тулбар вьюпорта */}
      <div style={{
        height: '44px',
        padding: '0 16px',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'rgba(17, 23, 38, 0.4)',
        zIndex: 10,
        flexShrink: 0
      }}>
        {/* Левая часть: Статус стрима и URL */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
          <Monitor size={16} color="var(--text-muted)" />
          <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)', whiteSpace: 'nowrap' }}>
            Демонстрация mdAgent
          </span>

          {isRunning && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '2px 8px',
              borderRadius: 'var(--radius-full)',
              background: 'rgba(16, 185, 129, 0.15)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              fontSize: '11px',
              fontWeight: '600',
              color: '#34d399',
              flexShrink: 0
            }}>
              <span className="live-dot" />
              CDP LIVE
            </div>
          )}

          {currentUrl && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              fontSize: '11px',
              color: 'var(--text-faint)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: '360px'
            }}>
              <Globe size={11} />
              <span>{currentUrl}</span>
            </div>
          )}
        </div>

        {/* Правая часть: Управление интерактивом и скриншотом */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {isRunning && (
            <>
              {/* Переключатель Интерактивного режима */}
              <button
                onClick={() => setInteractiveMode(!interactiveMode)}
                className={`btn ${interactiveMode ? 'btn-primary' : ''}`}
                style={{
                  padding: '4px 10px',
                  fontSize: '11px',
                  background: interactiveMode ? 'var(--accent-primary)' : 'var(--bg-surface)'
                }}
                title={interactiveMode ? 'Интерактивное управление активно: кликайте прямо по экрану' : 'Включить клики'}
              >
                <MousePointer size={13} />
                {interactiveMode ? 'Интерактив ON' : 'Интерактив'}
              </button>

              {/* Обновить снимок экрана */}
              <button
                onClick={handleManualRefresh}
                className="btn btn-icon"
                style={{ padding: '6px' }}
                title="Обновить снимок экрана"
              >
                <RotateCw size={14} style={{ animation: isRefreshing ? 'spin 0.6s linear infinite' : 'none' }} />
              </button>
            </>
          )}

          {/* Полноэкранный режим */}
          <button
            onClick={toggleFullscreen}
            className="btn btn-icon"
            style={{ padding: '6px' }}
            title={isFullscreen ? 'Выйти из полноэкранного режима' : 'На весь экран'}
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* Экран стрима (жестко зафиксированный без дерганий и скачков) */}
      <div 
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '16px',
          overflow: 'hidden',
          background: 'radial-gradient(circle at 50% 50%, #151b2e 0%, #0a0d14 100%)',
          position: 'relative'
        }}
        onWheel={handleWheel}
      >
        {screenImage ? (
          <div className="stream-screen-container">
            <div className={`stream-screen-box ${interactiveMode ? 'interactive' : ''}`}>
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
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-muted)',
            textAlign: 'center',
            maxWidth: '360px'
          }}>
            <div style={{
              width: '56px',
              height: '56px',
              borderRadius: '16px',
              background: 'rgba(255, 255, 255, 0.04)',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '16px'
            }}>
              <Monitor size={28} color="var(--text-faint)" />
            </div>
            <div style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-main)', marginBottom: '6px' }}>
              {isStartingSession 
                ? 'Запуск Chromium...' 
                : isRunning 
                  ? 'Ожидание видеопотока...' 
                  : 'Браузер не запущен'}
            </div>
            <div style={{ fontSize: '12px', lineHeight: '1.5', marginBottom: '18px' }}>
              {isStartingSession
                ? 'Инициализация браузера и подключение к сессии Tilda...'
                : isRunning 
                  ? 'Подключение к экрану Chromium...' 
                  : 'Запустите сессию Chromium, чтобы наблюдать за работой агента в реальном времени и управлять сайтом.'}
            </div>
            {!isRunning ? (
              <button 
                className="btn btn-primary" 
                onClick={onStartSession}
                disabled={isStartingSession}
                style={isStartingSession ? { opacity: 0.75, cursor: 'not-allowed' } : {}}
              >
                {isStartingSession ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    Запуск сессии...
                  </>
                ) : (
                  <>
                    <Play size={14} />
                    Запустить сессию
                  </>
                )}
              </button>
            ) : (
              <button className="btn" onClick={handleManualRefresh}>
                <RotateCw size={14} />
                Запросить кадр
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
