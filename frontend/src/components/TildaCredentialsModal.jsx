import React, { useState, useEffect } from 'react';
import { X, KeyRound, Eye, EyeOff, ShieldCheck } from 'lucide-react';

export default function TildaCredentialsModal({
  isOpen,
  onClose,
  initialEmail = '',
  initialPassword = '',
  onSave
}) {
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState(initialPassword);
  const [showPassword, setShowPassword] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setEmail(initialEmail || '');
      setPassword(initialPassword || '');
    }
  }, [isOpen, initialEmail, initialPassword]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      await onSave(email.trim(), password.trim());
      onClose();
    } catch (err) {
      console.error('Ошибка сохранения данных Tilda:', err);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="figma-modal-overlay" onClick={onClose}>
      <div className="figma-modal-card" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
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
              <KeyRound size={18} />
            </div>
            <div>
              <div className="figma-modal-title">Аккаунт Tilda</div>
              <div className="figma-modal-subtitle">Авторизация для управления сайтом</div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#9CA3AF',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div className="figma-form-group">
            <label className="figma-form-label">Email в Tilda</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              required
              className="figma-form-input"
              autoFocus
            />
          </div>

          <div className="figma-form-group">
            <label className="figma-form-label">Пароль в Tilda</label>
            <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                required
                className="figma-form-input"
                style={{ paddingRight: '36px' }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: 'absolute',
                  right: '10px',
                  background: 'transparent',
                  border: 'none',
                  color: '#9CA3AF',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '11px',
            color: '#6B7280',
            background: '#F9FAFB',
            padding: '8px 10px',
            borderRadius: '6px'
          }}>
            <ShieldCheck size={14} color="#10B981" />
            <span>Данные сохраняются локально для текущей активной сессии</span>
          </div>

          <div className="figma-modal-actions">
            <button
              type="button"
              className="figma-btn-cancel"
              onClick={onClose}
            >
              Отмена
            </button>
            <button
              type="submit"
              className="figma-btn-save"
              disabled={isSaving}
            >
              {isSaving ? 'Сохранение...' : 'Сохранить данные'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
