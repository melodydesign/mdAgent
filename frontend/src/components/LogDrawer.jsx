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
      background: 'rgba(255, 255, 255, 0.65)',
      backdropFilter: 'blur(24px)',
      WebkitBackdropFilter: 'blur(24px)',
      border: '1px solid rgba(255, 255, 255, 0.8)',
      borderRadius: '14px',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.03)',
      transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
      display: 'flex',
      flexDirection: 'column',
      height: isOpen ? '220px' : '40px',
      overflow: 'hidden',
      zIndex: 50,
      flexShrink: 0
    }}>
      {/* Шапка консоли логов */}
      <div 
        style={{
          height: '40px',
          padding: '0 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          background: 'transparent',
          userSelect: 'none'
        }}
        onClick={() => setIsOpen(!isOpen)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
          <div style={{
            width: '24px',
            height: '24px',
            borderRadius: '6px',
            background: '#EDE9FE',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#7C3AED'
          }}>
            <Terminal size={13} />
          </div>
          <span style={{ fontSize: '12px', fontWeight: '600', color: '#1F2937' }}>Системный журнал</span>
          <span style={{
            fontSize: '11px',
            background: 'rgba(124, 58, 237, 0.08)',
            padding: '1px 7px',
            borderRadius: '10px',
            color: '#7C3AED',
            fontWeight: '600'
          }}>
            {logs.length}
          </span>

          {/* Превью последнего лога в свернутом виде */}
          {!isOpen && lastLog && (
            <span style={{
              fontSize: '11.5px',
              color: lastLog.level === 'error' ? '#EF4444' : '#6B7280',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              marginLeft: '8px'
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
                      padding: '3px 8px',
                      fontSize: '10px',
                      borderRadius: '6px',
                      border: 'none',
                      cursor: 'pointer',
                      background: filter === lvl ? '#EDE9FE' : 'rgba(0, 0, 0, 0.04)',
                      color: filter === lvl ? '#7C3AED' : '#6B7280',
                      textTransform: 'uppercase',
                      fontWeight: '600',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    {lvl === 'all' ? 'Все' : lvl}
                  </button>
                ))}
              </div>

              {/* Копирование */}
              <button
                type="button"
                className="figma-icon-action-btn"
                onClick={copyLogs}
                style={{ width: '26px', height: '26px', borderRadius: '6px' }}
                title="Скопировать логи"
              >
                {copied ? <Check size={13} color="#10B981" /> : <Copy size={13} />}
              </button>

              {/* Очистка */}
              <button
                type="button"
                className="figma-icon-action-btn"
                onClick={onClearLogs}
                style={{ width: '26px', height: '26px', borderRadius: '6px' }}
                title="Очистить логи"
              >
                <Trash2 size={13} />
              </button>
            </>
          )}

          <div style={{
            width: '26px',
            height: '26px',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#6B7280'
          }}>
            {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </div>
        </div>
      </div>

      {/* Список логов при раскрытии */}
      {isOpen && (
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '10px 16px',
          fontSize: '11.5px',
          display: 'flex',
          flexDirection: 'column',
          gap: '5px',
          background: 'rgba(255, 255, 255, 0.55)',
          borderTop: '1px solid rgba(0, 0, 0, 0.05)'
        }}>
          {filteredLogs.length === 0 ? (
            <div style={{ color: '#9CA3AF', padding: '10px 0', textAlign: 'center' }}>
              Нет записей в журнале.
            </div>
          ) : (
            filteredLogs.map((log, idx) => {
              let tagBg = '#F3F4F6';
              let tagColor = '#6B7280';
              if (log.level === 'error') { tagBg = '#FEE2E2'; tagColor = '#EF4444'; }
              if (log.level === 'success') { tagBg = '#DCFCE7'; tagColor = '#15803D'; }
              if (log.level === 'warning') { tagBg = '#FEF3C7'; tagColor = '#D97706'; }

              return (
                <div key={idx} style={{ display: 'flex', alignItems: 'baseline', gap: '8px', lineHeight: '1.45' }}>
                  <span style={{ color: '#9CA3AF', fontSize: '10.5px', flexShrink: 0 }}>[{log.time}]</span>
                  <span style={{
                    background: tagBg,
                    color: tagColor,
                    fontSize: '10px',
                    padding: '1px 5px',
                    borderRadius: '4px',
                    textTransform: 'uppercase',
                    fontWeight: '600',
                    flexShrink: 0
                  }}>
                    {log.level}
                  </span>
                  <span style={{ color: '#1F2937', wordBreak: 'break-all' }}>
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
