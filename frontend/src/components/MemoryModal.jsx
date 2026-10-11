import React, { useState, useEffect } from 'react';
import { X, Brain, CheckCircle, Clock, ListOrdered, Layers } from 'lucide-react';

export default function MemoryModal({ isOpen, onClose }) {
  const [playbooks, setPlaybooks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedPlaybook, setSelectedPlaybook] = useState(null);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetch('/api/memory')
        .then(res => res.json())
        .then(data => {
          const list = data.playbooks || [];
          setPlaybooks(list);
          if (list.length > 0) setSelectedPlaybook(list[0]);
        })
        .catch(err => console.error('Ошибка загрузки памяти:', err))
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" style={{ maxWidth: '720px' }} onClick={(e) => e.stopPropagation()}>
        {/* Шапка */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Brain size={18} color="var(--accent-primary)" />
            <h3 style={{ fontSize: '15px', fontWeight: '600' }}>Память навыков и сценариев (Playbooks)</h3>
          </div>
          <button className="btn btn-icon" onClick={onClose} style={{ padding: '4px' }}>
            <X size={16} />
          </button>
        </div>

        {/* Тело */}
        <div style={{ display: 'flex', height: '380px' }}>
          {/* Список слева */}
          <div style={{
            width: '240px',
            borderRight: '1px solid var(--border-subtle)',
            overflowY: 'auto',
            padding: '10px'
          }}>
            {loading ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
                Загрузка сценариев...
              </div>
            ) : playbooks.length === 0 ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
                Пока нет сохраненных сценариев.
              </div>
            ) : (
              playbooks.map(pb => (
                <div
                  key={pb.id}
                  onClick={() => setSelectedPlaybook(pb)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-sm)',
                    marginBottom: '6px',
                    cursor: 'pointer',
                    background: selectedPlaybook?.id === pb.id ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
                    border: selectedPlaybook?.id === pb.id ? '1px solid rgba(99, 102, 241, 0.3)' : '1px solid transparent',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <div style={{
                    fontSize: '12px',
                    fontWeight: '600',
                    color: selectedPlaybook?.id === pb.id ? '#a5b4fc' : 'var(--text-main)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis'
                  }}>
                    {pb.name}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-faint)', marginTop: '2px' }}>
                    {pb.actions?.length || 0} шагов • {pb.use_count || 1} выполнений
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Детали справа */}
          <div style={{ flex: 1, padding: '16px', overflowY: 'auto' }}>
            {selectedPlaybook ? (
              <div>
                <div style={{ marginBottom: '14px' }}>
                  <h4 style={{ fontSize: '15px', fontWeight: '700', marginBottom: '4px' }}>
                    {selectedPlaybook.name}
                  </h4>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Триггер: «{selectedPlaybook.trigger || selectedPlaybook.name}»
                  </div>
                </div>

                <div style={{ fontSize: '12px', fontWeight: '600', marginBottom: '8px', color: 'var(--text-main)' }}>
                  Последовательность эталонных действий:
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {(selectedPlaybook.actions || []).map((act, i) => (
                    <div
                      key={i}
                      style={{
                        padding: '8px 12px',
                        background: 'var(--bg-surface-elevated)',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: '12px',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '8px'
                      }}
                    >
                      <span style={{
                        width: '20px',
                        height: '20px',
                        borderRadius: '50%',
                        background: 'rgba(99, 102, 241, 0.2)',
                        color: '#a5b4fc',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '11px',
                        fontWeight: '600',
                        flexShrink: 0
                      }}>
                        {i + 1}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: '600', color: 'var(--text-main)' }}>
                          {act.action}
                        </div>
                        {act.params && Object.keys(act.params).length > 0 && (
                          <div style={{
                            fontSize: '11px',
                            color: 'var(--text-muted)',
                            fontFamily: 'var(--font-mono)',
                            marginTop: '4px',
                            wordBreak: 'break-all',
                            overflowWrap: 'anywhere',
                            whiteSpace: 'pre-wrap',
                            background: 'rgba(0, 0, 0, 0.25)',
                            padding: '4px 8px',
                            borderRadius: '4px',
                            border: '1px solid rgba(255, 255, 255, 0.04)'
                          }}>
                            {JSON.stringify(act.params, null, 2)}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-faint)', fontSize: '12px' }}>
                Выберите навык для просмотра деталей
              </div>
            )}
          </div>
        </div>

        {/* Футер */}
        <div style={{
          padding: '12px 20px',
          borderTop: '1px solid var(--border-subtle)',
          display: 'flex',
          justifyContent: 'flex-end',
          background: 'rgba(10, 13, 20, 0.4)'
        }}>
          <button className="btn" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
