import React, { useState, useEffect } from 'react';
import { X, Check, Cpu, Zap, Shield, Sparkles } from 'lucide-react';

export default function SettingsModal({
  isOpen,
  onClose,
  activeProvider,
  settingsData,
  onSaveProvider
}) {
  const [selected, setSelected] = useState(activeProvider || 'hydraai');
  const [saving, setSaving] = useState(false);

  // Синхронизируем выбор с актуальным провайдером при каждом открытии окна
  useEffect(() => {
    if (isOpen) {
      setSelected(activeProvider || 'hydraai');
    }
  }, [isOpen, activeProvider]);

  if (!isOpen) return null;

  const handleSave = async () => {
    setSaving(true);
    await onSaveProvider(selected);
    setSaving(false);
    onClose();
  };

  const providers = settingsData?.providers || [
    {
      id: 'gemini',
      name: 'Google Gemini (Каскад)',
      active_model: 'gemini-3.8-flash',
      cascade: [
        { model: 'gemini-3.8-flash', rpm_limit: 15, rpd_limit: 1500, status: 'active' },
        { model: 'gemini-3.7-flash', rpm_limit: 15, rpd_limit: 1500, status: 'standby' },
        { model: 'gemini-3.6-flash', rpm_limit: 15, rpd_limit: 1500, status: 'standby' },
        { model: 'gemini-3-flash-preview', rpm_limit: 15, rpd_limit: 1500, status: 'standby' },
      ]
    },
    {
      id: 'hydraai',
      name: 'HydraAI (GPT-5.6 Luna)',
      model: 'gpt-5.6-luna',
      info: {
        speed: '87.07 TPS',
        context: '256 000 токенов',
        features: ['Vision', 'Reasoning', 'GPT-5.6 Architecture']
      }
    }
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Заголовок */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={18} color="var(--accent-primary)" />
            <h3 style={{ fontSize: '15px', fontWeight: '600' }}>Настройки AI Интеллекта</h3>
          </div>
          <button className="btn btn-icon" onClick={onClose} style={{ padding: '4px' }}>
            <X size={16} />
          </button>
        </div>

        {/* Контент */}
        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Выберите активную нейросеть для распознавания элементов Tilda и построения плана действий.
          </div>

          {/* Карточка Gemini */}
          <div 
            onClick={() => setSelected('gemini')}
            style={{
              padding: '14px',
              borderRadius: 'var(--radius-md)',
              border: selected === 'gemini' ? '2px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
              background: selected === 'gemini' ? 'rgba(99, 102, 241, 0.08)' : 'var(--bg-surface-elevated)',
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Zap size={16} color="var(--accent-primary)" />
                <span style={{ fontWeight: '600', fontSize: '14px' }}>Google Gemini (Каскад 3.8 → 3.0)</span>
              </div>
              {selected === 'gemini' && <Check size={16} color="var(--accent-primary)" />}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '10px' }}>
              Каскадный отказоустойчивый пул из 4 новейших моделей с защитой от лимитов (RPM/RPD).
            </div>

            {/* Список ступеней */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {['3.8 Flash (Основная)', '3.7 Flash', '3.6 Flash', '3.0 Flash Preview'].map((step, i) => (
                <span key={i} style={{
                  fontSize: '10px',
                  background: i === 0 ? 'rgba(99, 102, 241, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                  color: i === 0 ? '#a5b4fc' : 'var(--text-faint)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  border: '1px solid var(--border-subtle)'
                }}>
                  {step}
                </span>
              ))}
            </div>
          </div>

          {/* Карточка HydraAI */}
          <div 
            onClick={() => setSelected('hydraai')}
            style={{
              padding: '14px',
              borderRadius: 'var(--radius-md)',
              border: selected === 'hydraai' ? '2px solid var(--accent-secondary)' : '1px solid var(--border-subtle)',
              background: selected === 'hydraai' ? 'rgba(6, 182, 212, 0.08)' : 'var(--bg-surface-elevated)',
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={16} color="var(--accent-secondary)" />
                <span style={{ fontWeight: '600', fontSize: '14px' }}>HydraAI (GPT-5.6 Luna)</span>
                <span style={{
                  fontSize: '10px',
                  background: 'rgba(6, 182, 212, 0.2)',
                  color: '#67e8f9',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  fontWeight: '600'
                }}>
                  87 TPS
                </span>
              </div>
              {selected === 'hydraai' && <Check size={16} color="var(--accent-secondary)" />}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
              Флагманская модель GPT-5.6 Luna с контекстным окном 256k токенов и мгновенной генерацией.
            </div>
            <div style={{ display: 'flex', gap: '8px', fontSize: '11px', color: 'var(--text-faint)' }}>
              <span>• Vision Режим</span>
              <span>• Глубокий Reasoning</span>
              <span>• Высокая скорость</span>
            </div>
          </div>
        </div>

        {/* Футер */}
        <div style={{
          padding: '14px 20px',
          borderTop: '1px solid var(--border-subtle)',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: '10px',
          background: 'rgba(10, 13, 20, 0.4)'
        }}>
          <button className="btn" onClick={onClose} disabled={saving}>
            Отмена
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Сохранение...' : 'Применить'}
          </button>
        </div>
      </div>
    </div>
  );
}
