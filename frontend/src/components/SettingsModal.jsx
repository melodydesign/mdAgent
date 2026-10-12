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
              <Cpu size={18} />
            </div>
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>Настройки AI Интеллекта</h3>
              <div style={{ fontSize: '12px', color: '#6B7280' }}>Выбор активной нейросети для распознавания Tilda</div>
            </div>
          </div>
          <button className="btn btn-icon" onClick={onClose} style={{ padding: '4px' }}>
            <X size={16} />
          </button>
        </div>

        {/* Контент */}
        <div style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: '14px', background: '#ffffff' }}>
          {/* Карточка Gemini */}
          <div 
            onClick={() => setSelected('gemini')}
            style={{
              padding: '16px',
              borderRadius: '14px',
              border: selected === 'gemini' ? '2px solid #7C3AED' : '1px solid #E5E7EB',
              background: selected === 'gemini' ? '#F5F3FF' : '#F9FAFB',
              cursor: 'pointer',
              transition: 'all 0.18s ease',
              boxShadow: selected === 'gemini' ? '0 4px 14px rgba(124, 58, 237, 0.08)' : 'none'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Zap size={17} color="#7C3AED" />
                <span style={{ fontWeight: '700', fontSize: '14px', color: '#111827' }}>Google Gemini (Каскад 3.8 → 3.0)</span>
              </div>
              <div style={{
                width: '20px',
                height: '20px',
                borderRadius: '50%',
                border: selected === 'gemini' ? 'none' : '1.5px solid #D1D5DB',
                background: selected === 'gemini' ? '#7C3AED' : '#ffffff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#ffffff'
              }}>
                {selected === 'gemini' && <Check size={13} strokeWidth={3} />}
              </div>
            </div>
            <div style={{ fontSize: '12px', color: '#4B5563', marginBottom: '12px', lineHeight: '1.4' }}>
              Каскадный отказоустойчивый пул из 4 новейших моделей с защитой от лимитов (RPM/RPD).
            </div>

            {/* Список ступеней */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {['3.8 Flash (Основная)', '3.7 Flash', '3.6 Flash', '3.0 Flash Preview'].map((step, i) => (
                <span key={i} style={{
                  fontSize: '11px',
                  background: i === 0 ? '#EDE9FE' : '#ffffff',
                  color: i === 0 ? '#6D28D9' : '#6B7280',
                  fontWeight: i === 0 ? '600' : '400',
                  padding: '3px 8px',
                  borderRadius: '6px',
                  border: i === 0 ? '1px solid #DDD6FE' : '1px solid #E5E7EB'
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
              padding: '16px',
              borderRadius: '14px',
              border: selected === 'hydraai' ? '2px solid #7C3AED' : '1px solid #E5E7EB',
              background: selected === 'hydraai' ? '#F5F3FF' : '#F9FAFB',
              cursor: 'pointer',
              transition: 'all 0.18s ease',
              boxShadow: selected === 'hydraai' ? '0 4px 14px rgba(124, 58, 237, 0.08)' : 'none'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={17} color="#7C3AED" />
                <span style={{ fontWeight: '700', fontSize: '14px', color: '#111827' }}>HydraAI (GPT-5.6 Luna)</span>
                <span style={{
                  fontSize: '10px',
                  background: '#EDE9FE',
                  color: '#6D28D9',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  fontWeight: '600'
                }}>
                  87 TPS
                </span>
              </div>
              <div style={{
                width: '20px',
                height: '20px',
                borderRadius: '50%',
                border: selected === 'hydraai' ? 'none' : '1.5px solid #D1D5DB',
                background: selected === 'hydraai' ? '#7C3AED' : '#ffffff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#ffffff'
              }}>
                {selected === 'hydraai' && <Check size={13} strokeWidth={3} />}
              </div>
            </div>
            <div style={{ fontSize: '12px', color: '#4B5563', marginBottom: '10px', lineHeight: '1.4' }}>
              Флагманская модель GPT-5.6 Luna с контекстным окном 256k токенов и мгновенной генерацией.
            </div>
            <div style={{ display: 'flex', gap: '10px', fontSize: '11px', color: '#6B7280' }}>
              <span>• Vision Режим</span>
              <span>• Глубокий Reasoning</span>
              <span>• Высокая скорость</span>
            </div>
          </div>
        </div>

        {/* Футер */}
        <div style={{
          padding: '16px 22px',
          borderTop: '1px solid #F3F4F6',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: '10px',
          background: '#FAFAFB'
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
