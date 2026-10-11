import React, { useState, useEffect } from 'react';
import { 
  ArrowLeft, 
  Plus, 
  Trash2, 
  Edit3, 
  Check, 
  X, 
  MessageSquare, 
  Key, 
  Eye, 
  EyeOff, 
  CheckCircle2, 
  Clock 
} from 'lucide-react';

export default function DialogsPanel({ activeSessionId, onSelectSession, onBackToChat }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  // Состояние создания
  const [isCreating, setIsCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);

  // Состояние редактирования
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [editEmail, setEditEmail] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [showEditPassword, setShowEditPassword] = useState(false);

  // Подтверждение удаления
  const [deletingId, setDeletingId] = useState(null);

  const fetchSessions = async () => {
    try {
      const res = await fetch('/api/chat/sessions');
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch (e) {
      console.warn('Ошибка загрузки сессий:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleCreate = async (e) => {
    e?.preventDefault();
    const title = newTitle.trim() || 'Новый диалог';
    try {
      const res = await fetch('/api/chat/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          tilda_email: newEmail.trim(),
          tilda_password: newPassword.trim()
        })
      });
      if (res.ok) {
        const data = await res.json();
        setIsCreating(false);
        setNewTitle('');
        setNewEmail('');
        setNewPassword('');
        setSessions(data.sessions || []);
        if (data.session) {
          onSelectSession?.(data.session.id);
        }
      }
    } catch (err) {
      console.error('Ошибка создания диалога:', err);
    }
  };

  const handleStartEdit = (s, e) => {
    e?.stopPropagation();
    setEditingId(s.id);
    setEditTitle(s.title || '');
    setEditEmail(s.tilda_email || '');
    setEditPassword(s.tilda_password || '');
    setShowEditPassword(false);
  };

  const handleSaveEdit = async (id, e) => {
    e?.stopPropagation();
    try {
      const res = await fetch(`/api/chat/sessions/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: editTitle.trim() || 'Без названия',
          tilda_email: editEmail.trim(),
          tilda_password: editPassword.trim()
        })
      });
      if (res.ok) {
        setEditingId(null);
        await fetchSessions();
      }
    } catch (err) {
      console.error('Ошибка обновления диалога:', err);
    }
  };

  const handleDelete = async (id, e) => {
    e?.stopPropagation();
    try {
      const res = await fetch(`/api/chat/sessions/${id}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        setDeletingId(null);
        await fetchSessions();
      }
    } catch (err) {
      console.error('Ошибка удаления диалога:', err);
    }
  };

  const handleSelect = (id) => {
    if (editingId) return;
    onSelectSession?.(id);
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border-subtle)'
    }}>
      {/* Шапка списка диалогов */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'rgba(17, 23, 38, 0.6)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            type="button"
            className="btn btn-icon"
            onClick={onBackToChat}
            title="Вернуться к текущему чату"
            style={{ padding: '6px' }}
          >
            <ArrowLeft size={16} />
          </button>
          <span style={{ fontWeight: '600', fontSize: '14px' }}>Список диалогов</span>
          <span style={{
            fontSize: '11px',
            background: 'rgba(255, 255, 255, 0.08)',
            padding: '2px 6px',
            borderRadius: '10px',
            color: 'var(--text-muted)'
          }}>
            {sessions.length}
          </span>
        </div>

        {!isCreating && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setIsCreating(true)}
            style={{ padding: '6px 12px', fontSize: '12px', gap: '5px' }}
            title="Создать новый чистый диалог"
          >
            <Plus size={14} />
            Новый
          </button>
        )}
      </div>

      {/* Форма создания нового диалога */}
      {isCreating && (
        <form onSubmit={handleCreate} style={{
          margin: '12px 14px',
          padding: '14px',
          background: 'var(--bg-surface-elevated)',
          border: '1px solid var(--border-glow)',
          borderRadius: 'var(--radius-md)',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}>
          <div style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Plus size={14} color="var(--accent-primary)" />
            Новый диалог
          </div>

          <div>
            <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
              Название диалога
            </label>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Например: Лендинг для кофе (ST205)"
              autoFocus
              className="dialog-input"
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                Email Tilda (опционально)
              </label>
              <input
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder="user@example.com"
                className="dialog-input"
              />
            </div>
            <div>
              <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                Пароль Tilda (опционально)
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type={showNewPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="••••••••"
                  className="dialog-input"
                  style={{ paddingRight: '28px' }}
                />
                <button
                  type="button"
                  onClick={() => setShowNewPassword(!showNewPassword)}
                  style={{
                    position: 'absolute',
                    right: '6px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-faint)',
                    cursor: 'pointer',
                    padding: '2px'
                  }}
                >
                  {showNewPassword ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '4px' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsCreating(false)}
              style={{ fontSize: '12px', padding: '6px 12px' }}
            >
              Отмена
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              style={{ fontSize: '12px', padding: '6px 14px' }}
            >
              Создать и открыть
            </button>
          </div>
        </form>
      )}

      {/* Список диалогов */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px'
      }}>
        {loading ? (
          <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
            Загрузка диалогов...
          </div>
        ) : sessions.length === 0 ? (
          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-muted)' }}>
            <MessageSquare size={32} color="var(--text-faint)" style={{ margin: '0 auto 10px' }} />
            <div style={{ fontSize: '13px', fontWeight: '500' }}>Нет диалогов</div>
            <div style={{ fontSize: '11px', marginTop: '4px' }}>Нажмите «Новый», чтобы начать</div>
          </div>
        ) : (
          sessions.map((s) => {
            const isActive = s.id === activeSessionId;
            const isEditing = editingId === s.id;
            const isDeleting = deletingId === s.id;
            const msgCount = s.messages_count || (s.messages ? s.messages.length : 0);
            const hasCustomTilda = Boolean(s.tilda_email);

            return (
              <div
                key={s.id}
                onClick={() => handleSelect(s.id)}
                className={`dialog-card ${isActive ? 'active' : ''}`}
              >
                {isEditing ? (
                  // Форма inline-редактирования сессии
                  <div 
                    onClick={(e) => e.stopPropagation()} 
                    style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}
                  >
                    <div>
                      <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>
                        Название диалога
                      </label>
                      <input
                        type="text"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        className="dialog-input"
                      />
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                      <div>
                        <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>
                          Email Tilda
                        </label>
                        <input
                          type="email"
                          value={editEmail}
                          onChange={(e) => setEditEmail(e.target.value)}
                          placeholder="user@example.com"
                          className="dialog-input"
                        />
                      </div>
                      <div>
                        <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>
                          Пароль Tilda
                        </label>
                        <div style={{ position: 'relative' }}>
                          <input
                            type={showEditPassword ? 'text' : 'password'}
                            value={editPassword}
                            onChange={(e) => setEditPassword(e.target.value)}
                            placeholder="••••••••"
                            className="dialog-input"
                            style={{ paddingRight: '24px' }}
                          />
                          <button
                            type="button"
                            onClick={() => setShowEditPassword(!showEditPassword)}
                            style={{
                              position: 'absolute',
                              right: '4px',
                              top: '50%',
                              transform: 'translateY(-50%)',
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-faint)',
                              cursor: 'pointer'
                            }}
                          >
                            {showEditPassword ? <EyeOff size={11} /> : <Eye size={11} />}
                          </button>
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end', marginTop: '4px' }}>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => setEditingId(null)}
                        style={{ padding: '4px 8px', fontSize: '11px' }}
                      >
                        Отмена
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={(e) => handleSaveEdit(s.id, e)}
                        style={{ padding: '4px 10px', fontSize: '11px', gap: '4px' }}
                      >
                        <Check size={12} />
                        Сохранить
                      </button>
                    </div>
                  </div>
                ) : (
                  // Обычный вид карточки
                  <>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '6px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
                        <span style={{
                          fontWeight: isActive ? '600' : '500',
                          fontSize: '13px',
                          color: 'var(--text-main)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis'
                        }}>
                          {s.title || 'Диалог'}
                        </span>
                        {isActive && (
                          <span style={{
                            fontSize: '10px',
                            padding: '1px 6px',
                            background: 'rgba(99, 102, 241, 0.25)',
                            color: '#a5b4fc',
                            borderRadius: '4px',
                            fontWeight: '600',
                            flexShrink: 0
                          }}>
                            Активен
                          </span>
                        )}
                      </div>

                      <div className="dialog-actions" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="btn btn-icon"
                          onClick={(e) => handleStartEdit(s, e)}
                          title="Редактировать название и доступы Tilda"
                          style={{ padding: '4px', color: 'var(--text-muted)' }}
                        >
                          <Edit3 size={13} />
                        </button>
                        <button
                          type="button"
                          className="btn btn-icon"
                          onClick={(e) => setDeletingId(s.id)}
                          title="Удалить диалог"
                          style={{ padding: '4px', color: 'var(--text-muted)' }}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>

                    {isDeleting ? (
                      <div 
                        onClick={(e) => e.stopPropagation()} 
                        style={{
                          marginTop: '6px',
                          padding: '6px 8px',
                          background: 'rgba(239, 68, 68, 0.1)',
                          border: '1px solid rgba(239, 68, 68, 0.25)',
                          borderRadius: '6px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '6px'
                        }}
                      >
                        <span style={{ fontSize: '11px', color: '#fca5a5' }}>Удалить этот диалог?</span>
                        <div style={{ display: 'flex', gap: '4px' }}>
                          <button
                            type="button"
                            onClick={() => setDeletingId(null)}
                            style={{ padding: '2px 6px', fontSize: '10.5px', background: 'transparent', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '4px', color: '#fff', cursor: 'pointer' }}
                          >
                            Нет
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleDelete(s.id, e)}
                            style={{ padding: '2px 6px', fontSize: '10.5px', background: 'var(--accent-danger)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer' }}
                          >
                            Да, удалить
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginTop: '6px',
                        fontSize: '11px',
                        color: 'var(--text-faint)'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span>{msgCount} сообщ.</span>
                          {hasCustomTilda && (
                            <span style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '3px',
                              color: 'var(--accent-secondary)',
                              background: 'rgba(6, 182, 212, 0.12)',
                              padding: '1px 5px',
                              borderRadius: '4px'
                            }} title={`Собственный логин Tilda: ${s.tilda_email}`}>
                              <Key size={10} />
                              {s.tilda_email.split('@')[0]}
                            </span>
                          )}
                        </div>

                        {s.updated_at && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                            <Clock size={10} />
                            <span>{new Date(s.updated_at * 1000).toLocaleDateString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
