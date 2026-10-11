import React from 'react';
import { 
  Play, 
  Square, 
  Pause, 
  ExternalLink, 
  Brain, 
  Settings, 
  Zap, 
  Activity,
  Cpu,
  Loader2
} from 'lucide-react';

export default function Header({
  status,
  quotas,
  activeProvider,
  isStartingSession,
  onStart,
  onStop,
  onPause,
  onResume,
  onBringToFront,
  onOpenSettings,
  onOpenMemory
}) {
  const isRunning = Boolean(status?.browser?.is_running || status?.browser_running);
  const isBusy = Boolean(status?.is_busy);
  const isPaused = Boolean(status?.is_paused);

  // Форматирование статуса
  let statusText = 'Остановлен';
  let statusColor = 'var(--text-faint)';
  if (isStartingSession) {
    statusText = 'Запуск Chromium...';
    statusColor = 'var(--accent-warning)';
  } else if (isRunning) {
    if (isBusy) {
      statusText = isPaused ? 'На паузе' : 'Выполняет задачу...';
      statusColor = isPaused ? 'var(--accent-warning)' : 'var(--accent-primary)';
    } else {
      statusText = 'Готов к работе';
      statusColor = 'var(--accent-success)';
    }
  }

  const providerLabel = activeProvider === 'hydraai' 
    ? 'HydraAI Luna' 
    : 'Gemini 3.8';

  return (
    <header style={{
      height: '64px',
      padding: '0 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      borderBottom: '1px solid var(--border-subtle)',
      background: 'rgba(10, 13, 20, 0.85)',
      backdropFilter: 'blur(12px)',
      zIndex: 100,
      position: 'relative'
    }}>
      {/* Левая часть: Бренд и статус */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '34px',
            height: '34px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, var(--accent-primary), #4338ca)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 10px rgba(99, 102, 241, 0.4)'
          }}>
            <Zap size={20} color="#fff" />
          </div>
          <div>
            <div style={{ fontSize: '16px', fontWeight: '700', letterSpacing: '-0.02em', display: 'flex', alignItems: 'center', gap: '6px' }}>
              mdAgent
              <span style={{ 
                fontSize: '10px', 
                background: 'rgba(99, 102, 241, 0.2)', 
                color: '#a5b4fc', 
                padding: '1px 6px', 
                borderRadius: '4px',
                fontWeight: '600'
              }}>
                v2.0 React
              </span>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              AI Tilda Automation Engine
            </div>
          </div>
        </div>

        {/* Разделитель */}
        <div style={{ width: '1px', height: '28px', background: 'var(--border-subtle)' }} />

        {/* Индикатор статуса */}
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: '8px', 
          padding: '4px 10px', 
          background: 'var(--bg-surface)', 
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border-subtle)'
        }}>
          <span style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: statusColor,
            boxShadow: isRunning && !isPaused ? `0 0 8px ${statusColor}` : 'none'
          }} />
          <span style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-main)' }}>
            {statusText}
          </span>
        </div>
      </div>

      {/* Центральная часть: Квоты и Модель */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Чип активного AI */}
        <button 
          onClick={onOpenSettings}
          className={`badge ${activeProvider === 'hydraai' ? 'badge-hydra' : 'badge-gemini'}`}
          style={{ cursor: 'pointer', border: 'none', padding: '6px 12px' }}
          title="Нажмите для смены нейросети"
        >
          <Cpu size={13} />
          <span>{providerLabel}</span>
        </button>

        {/* Квоты (RPM / RPD) */}
        {quotas && (
          <div style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: '8px', 
            fontSize: '11px', 
            color: 'var(--text-muted)',
            background: 'var(--bg-surface)',
            padding: '4px 10px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)'
          }}>
            <Activity size={12} color="var(--accent-secondary)" />
            <span>RPM: <strong style={{ color: quotas.rpm_remaining < 3 ? 'var(--accent-danger)' : 'var(--text-main)' }}>{quotas.rpm_remaining ?? 15}</strong>/{quotas.rpm_limit ?? 15}</span>
            <span style={{ opacity: 0.3 }}>|</span>
            <span>RPD: <strong style={{ color: 'var(--text-main)' }}>{quotas.rpd_remaining ?? 1500}</strong>/{quotas.rpd_limit ?? 1500}</span>
          </div>
        )}
      </div>

      {/* Правая часть: Управление сессией и модалками */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {/* Кнопка Старт / Стоп */}
        {!isRunning ? (
          <button 
            className="btn btn-primary" 
            onClick={onStart}
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
          <button className="btn btn-danger" onClick={onStop}>
            <Square size={14} />
            Остановить
          </button>
        )}

        {/* Пауза / Возобновить при выполнении */}
        {isRunning && isBusy && (
          isPaused ? (
            <button className="btn btn-success" onClick={onResume}>
              <Play size={14} />
              Продолжить
            </button>
          ) : (
            <button className="btn" onClick={onPause} style={{ color: 'var(--accent-warning)', borderColor: 'rgba(245, 158, 11, 0.3)' }}>
              <Pause size={14} />
              Пауза
            </button>
          )
        )}

        {/* Окно браузера на передний план */}
        {isRunning && (
          <button 
            className="btn" 
            onClick={onBringToFront} 
            title="Вывести окно Chromium на передний план рабочего стола Windows"
          >
            <ExternalLink size={14} />
            Окно Chromium
          </button>
        )}

        {/* Память сценариев */}
        <button 
          className="btn" 
          onClick={onOpenMemory}
          title="Выученные навыки и сценарии"
        >
          <Brain size={14} />
          Память
        </button>

        {/* Настройки AI */}
        <button 
          className="btn btn-icon" 
          onClick={onOpenSettings}
          title="Настройки AI провайдеров"
        >
          <Settings size={16} />
        </button>
      </div>

      {/* Неоновый бегунок загрузки сессии */}
      {isStartingSession && (
        <div className="header-runner-container">
          <div className="header-runner" />
        </div>
      )}
    </header>
  );
}
