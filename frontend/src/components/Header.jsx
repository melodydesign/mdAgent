import React from 'react';
import { 
  Settings, 
  Brain, 
  Terminal, 
  Wifi, 
  WifiOff, 
  SlidersHorizontal 
} from 'lucide-react';

export default function Header({
  status,
  activeProvider,
  onOpenSettings,
  onOpenMemory,
  onToggleLogs,
  userProfile = {
    name: 'Emerson Sterling',
    email: 'sterling@gmail.com',
    initials: 'ES'
  }
}) {
  const isOnline = Boolean(status?.is_ready ?? true);
  const isRunning = Boolean(status?.browser?.is_running || status?.browser_running);

  return (
    <header className="figma-header">
      {/* Левая часть: Профиль пользователя как в Figma */}
      <div className="figma-profile-section">
        <div className="figma-avatar">
          {userProfile.initials || 'ES'}
        </div>
        <div>
          <div className="figma-profile-name">
            {userProfile.name || 'Emerson Sterling'}
          </div>
          <div className="figma-profile-email">
            {userProfile.email || 'sterling@gmail.com'}
          </div>
        </div>
      </div>

      {/* Правая часть: Системные действия и настройки */}
      <div className="figma-header-actions">
        {/* Индикатор связи */}
        <div 
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '11px',
            padding: '4px 10px',
            borderRadius: '9999px',
            background: isOnline ? '#F0FDF4' : '#FEF2F2',
            color: isOnline ? '#166534' : '#991B1B',
            fontWeight: 500,
            marginRight: '6px'
          }}
          title={isOnline ? 'Подключено к WebSocket' : 'Потеря соединения'}
        >
          {isOnline ? <Wifi size={13} color="#16a34a" /> : <WifiOff size={13} color="#dc2626" />}
          <span>{isOnline ? 'Онлайн' : 'Офлайн'}</span>
        </div>

        {/* Память */}
        <button
          type="button"
          onClick={onOpenMemory}
          className="figma-header-btn"
          title="База знаний проверенных рецептов"
        >
          <Brain size={15} />
          <span>Рецепты</span>
        </button>

        {/* Настройки */}
        <button
          type="button"
          onClick={onOpenSettings}
          className="figma-header-btn"
          title="Конфигурация провайдеров и моделей"
        >
          <Settings size={15} />
          <span>Настройки</span>
        </button>

        {/* Логи */}
        {onToggleLogs && (
          <button
            type="button"
            onClick={onToggleLogs}
            className="figma-header-btn"
            title="Консоль действий и системных логов"
          >
            <Terminal size={15} />
            <span>Логи</span>
          </button>
        )}
      </div>
    </header>
  );
}
