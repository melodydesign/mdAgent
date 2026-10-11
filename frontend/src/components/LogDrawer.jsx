import React, { useState, useRef, useEffect } from 'react';
import { 
  Terminal, 
  ChevronUp, 
  ChevronDown, 
  Copy, 
  Trash2, 
  Check,
  Filter
} from 'lucide-react';

export default function LogDrawer({ logs, onClearLogs }) {
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState('all'); // all, info, success, error
  const [copied, setCopied] = useState(false);
  const logsEndRef = useRef(null);

  const filteredLogs = logs.filter(log => {
    if (filter === 'all') return true;
    return log.level === filter;
  });

  useEffect(() => {
    if (isOpen) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isOpen]);

  const fallbackCopy = (text) => {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      textarea.style.top = '-9999px';
      textarea.setAttribute('readonly', '');
      document.body.appendChild(textarea);
      textarea.select();
      const successful = document.execCommand('copy');
      document.body.removeChild(textarea);
      if (successful) {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch (err) {
      console.error('Fallback copy failed:', err);
    }
  };

  const copyLogs = (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    const text = logs.map(l => `[${l.time}] [${l.level.toUpperCase()}] ${l.message}`).join('\n');
    if (!text) return;

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }).catch(() => fallbackCopy(text));
    } else {
      fallbackCopy(text);
    }
  };

  const lastLog = logs.length > 0 ? logs[logs.length - 1] : null;

  return (
    <div style={{
      borderTop: '1px solid var(--border-subtle)',
      background: 'var(--bg-surface)',
      transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
      display: 'flex',
      flexDirection: 'column',
      height: isOpen ? '220px' : '38px',
      zIndex: 50
    }}>
      {/* Шапка консоли логов */}
      <div 
        style={{
          height: '38px',
          padding: '0 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          background: 'rgba(10, 13, 20, 0.6)',
          userSelect: 'none'
        }}
        onClick={() => setIsOpen(!isOpen)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
          <Terminal size={15} color="var(--accent-secondary)" />
          <span style={{ fontSize: '12px', fontWeight: '600' }}>Системный журнал</span>
          <span style={{
            fontSize: '11px',
            background: 'rgba(255, 255, 255, 0.06)',
            padding: '1px 6px',
            borderRadius: '10px',
            color: 'var(--text-muted)'
          }}>
            {logs.length}
          </span>

          {/* Превью последнего лога в свернутом виде */}
          {!isOpen && lastLog && (
            <span style={{
              fontSize: '11px',
              color: lastLog.level === 'error' ? 'var(--accent-danger)' : 'var(--text-muted)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              marginLeft: '10px',
              fontFamily: 'var(--font-mono)'
            }}>
              [{lastLog.time}] {lastLog.message}
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }} onClick={(e) => e.stopPropagation()}>
          {isOpen && (
            <>
              {/* Фильтры */}
              <div style={{ display: 'flex', gap: '4px', marginRight: '6px' }}>
                {['all', 'info', 'success', 'error'].map(lvl => (
                  <button
                    key={lvl}
                    onClick={() => setFilter(lvl)}
                    style={{
                      padding: '2px 8px',
                      fontSize: '10px',
                      borderRadius: '4px',
                      border: 'none',
                      cursor: 'pointer',
                      background: filter === lvl ? 'rgba(99, 102, 241, 0.3)' : 'transparent',
                      color: filter === lvl ? '#a5b4fc' : 'var(--text-muted)',
                      textTransform: 'uppercase',
                      fontWeight: '600'
                    }}
                  >
                    {lvl === 'all' ? 'Все' : lvl}
                  </button>
                ))}
              </div>

              {/* Копирование */}
              <button
                className="btn btn-icon"
                onClick={copyLogs}
                style={{ padding: '4px' }}
                title="Скопировать логи"
              >
                {copied ? <Check size={13} color="var(--accent-success)" /> : <Copy size={13} />}
              </button>

              {/* Очистка */}
              <button
                className="btn btn-icon"
                onClick={onClearLogs}
                style={{ padding: '4px' }}
                title="Очистить логи"
              >
                <Trash2 size={13} />
              </button>
            </>
          )}

          <button 
            className="btn btn-icon"
            onClick={() => setIsOpen(!isOpen)}
            style={{ padding: '4px' }}
          >
            {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
        </div>
      </div>

      {/* Список логов при раскрытии */}
      {isOpen && (
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 16px',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          background: 'var(--bg-base)'
        }}>
          {filteredLogs.length === 0 ? (
            <div style={{ color: 'var(--text-faint)', padding: '10px 0' }}>
              Нет записей в журнале.
            </div>
          ) : (
            filteredLogs.map((log, idx) => {
              let color = 'var(--text-muted)';
              if (log.level === 'error') color = 'var(--accent-danger)';
              if (log.level === 'success') color = 'var(--accent-success)';
              if (log.level === 'warning') color = 'var(--accent-warning)';

              return (
                <div key={idx} style={{ display: 'flex', gap: '8px', lineHeight: '1.4' }}>
                  <span style={{ color: 'var(--text-faint)', flexShrink: 0 }}>[{log.time}]</span>
                  <span style={{
                    color,
                    textTransform: 'uppercase',
                    fontWeight: '600',
                    width: '55px',
                    flexShrink: 0
                  }}>
                    {log.level}
                  </span>
                  <span style={{ color: 'var(--text-main)', wordBreak: 'break-all' }}>
                    {log.message}
                  </span>
                </div>
              );
            })
          )}
          <div ref={logsEndRef} />
        </div>
      )}
    </div>
  );
}
