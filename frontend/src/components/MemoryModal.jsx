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
      <div className="modal-card" style={{ maxWidth: '740px' }} onClick={(e) => e.stopPropagation()}>
        {/* Шапка */}
        <div style={{
          padding: '18px 22px',
          borderBottom: '1px solid #F3F4F6',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#ffffff'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: '#EDE9FE',
              color: '#7C3AED',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Brain size={18} />
            </div>
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>Память навыков и сценариев (Playbooks)</h3>
              <div style={{ fontSize: '12px', color: '#6B7280' }}>Автоматически изученные шаблоны действий на страницах Tilda</div>
            </div>
          </div>
          <button className="btn btn-icon" onClick={onClose} style={{ padding: '4px' }}>
            <X size={16} />
          </button>
        </div>

        {/* Тело */}
        <div style={{ display: 'flex', height: '420px', background: '#ffffff' }}>
          {/* Список слева */}
          <div style={{
            width: '260px',
            borderRight: '1px solid #F3F4F6',
            overflowY: 'auto',
            padding: '12px',
            background: '#FAFAFB'
          }}>
            {loading ? (
              <div style={{ padding: '24px 12px', textAlign: 'center', color: '#9CA3AF', fontSize: '12px' }}>
                Загрузка сценариев...
              </div>
            ) : playbooks.length === 0 ? (
              <div style={{ padding: '24px 12px', textAlign: 'center', color: '#9CA3AF', fontSize: '12px' }}>
                Пока нет сохраненных сценариев.
              </div>
            ) : (
              playbooks.map(pb => {
                const isSel = selectedPlaybook?.id === pb.id;
                return (
                  <div
                    key={pb.id}
                    onClick={() => setSelectedPlaybook(pb)}
                    style={{
                      padding: '11px 13px',
                      borderRadius: '10px',
                      marginBottom: '6px',
                      cursor: 'pointer',
                      background: isSel ? '#F5F3FF' : '#ffffff',
                      border: isSel ? '1.5px solid #7C3AED' : '1px solid #E5E7EB',
                      boxShadow: isSel ? '0 2px 8px rgba(124, 58, 237, 0.08)' : '0 1px 2px rgba(0,0,0,0.02)',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{
                      fontSize: '12.5px',
                      fontWeight: '600',
                      color: isSel ? '#6D28D9' : '#111827',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis'
                    }}>
                      {pb.name}
                    </div>
                    <div style={{ fontSize: '11px', color: '#6B7280', marginTop: '3px' }}>
                      {pb.actions?.length || 0} шагов • {pb.use_count || 1} выполнений
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Детали справа */}
          <div style={{ flex: 1, padding: '18px 22px', overflowY: 'auto', background: '#ffffff' }}>
            {selectedPlaybook ? (
              <div>
                <div style={{ marginBottom: '16px', paddingBottom: '12px', borderBottom: '1px solid #F3F4F6' }}>
                  <h4 style={{ fontSize: '16px', fontWeight: '700', color: '#111827', marginBottom: '4px' }}>
                    {selectedPlaybook.name}
                  </h4>
                  <div style={{ fontSize: '12px', color: '#6B7280' }}>
                    Триггер: <span style={{ color: '#7C3AED', fontWeight: '500' }}>«{selectedPlaybook.trigger || selectedPlaybook.name}»</span>
                  </div>
                </div>

                <div style={{ fontSize: '12px', fontWeight: '600', marginBottom: '10px', color: '#374151' }}>
                  Последовательность эталонных действий:
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {(selectedPlaybook.actions || []).map((act, i) => (
                    <div
                      key={i}
                      style={{
                        padding: '10px 12px',
                        background: '#F9FAFB',
                        borderRadius: '10px',
                        border: '1px solid #E5E7EB',
                        fontSize: '12px',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '10px'
                      }}
                    >
                      <span style={{
                        width: '22px',
                        height: '22px',
                        borderRadius: '50%',
                        background: '#EDE9FE',
                        color: '#7C3AED',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '11px',
                        fontWeight: '700',
                        flexShrink: 0
                      }}>
                        {i + 1}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: '600', color: '#111827' }}>
                          {act.action}
                        </div>
                        {act.params && Object.keys(act.params).length > 0 && (
                          <div style={{
                            fontSize: '11px',
                            color: '#334155',
                            fontFamily: 'var(--font-mono)',
                            marginTop: '6px',
                            wordBreak: 'break-all',
                            overflowWrap: 'anywhere',
                            whiteSpace: 'pre-wrap',
                            background: '#F1F5F9',
                            padding: '6px 10px',
                            borderRadius: '6px',
                            border: '1px solid #E2E8F0'
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
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#9CA3AF', fontSize: '13px' }}>
                Выберите навык слева для просмотра деталей
              </div>
            )}
          </div>
        </div>

        {/* Футер */}
        <div style={{
          padding: '14px 22px',
          borderTop: '1px solid #F3F4F6',
          display: 'flex',
          justifyContent: 'flex-end',
          background: '#FAFAFB'
        }}>
          <button className="btn btn-primary" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
