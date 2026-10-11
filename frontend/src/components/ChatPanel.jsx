import React, { useState, useRef, useEffect } from 'react';
import { 
  Send, 
  Trash2, 
  Bot, 
  User, 
  ExternalLink, 
  CheckCircle2, 
  AlertCircle, 
  Sparkles,
  Edit3,
  Check,
  X,
  Plus,
  PlusCircle,
  ArrowUp,
  ArrowDown,
  ChevronDown,
  ChevronUp,
  Copy,
  CornerUpLeft,
  ArrowDownLeft,
  Paperclip,
  Pen,
  Image as ImageIcon,
  MessageSquare,
  Maximize2
} from 'lucide-react';
import ImageAnnotatorModal from './ImageAnnotatorModal';

const formatStepsCount = (count) => {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 19) return `${count} шагов`;
  if (mod10 === 1) return `${count} шаг`;
  if (mod10 >= 2 && mod10 <= 4) return `${count} шага`;
  return `${count} шагов`;
};

function PlanConfirmationCard({
  planId,
  initialSteps = [],
  onConfirm,
  onCancel,
  isBusy,
  isHistorical = false
}) {
  const [steps, setSteps] = useState(initialSteps);
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState('');
  const [isSubmitted, setIsSubmitted] = useState(isHistorical);
  const [isCollapsed, setIsCollapsed] = useState(isHistorical);

  const activeCount = steps.filter(s => s.enabled).length;

  const handleToggleStep = (id, e) => {
    e?.stopPropagation();
    if (isSubmitted) return;
    setSteps(prev => prev.map(s => s.id === id ? { ...s, enabled: !s.enabled } : s));
  };

  const handleStartEdit = (step, e) => {
    e?.stopPropagation();
    if (isSubmitted) return;
    setEditingId(step.id);
    setEditText(step.text);
  };

  const handleSaveEdit = (id, e) => {
    e?.stopPropagation();
    if (!editText.trim()) return;
    setSteps(prev => prev.map(s => s.id === id ? { ...s, text: editText.trim() } : s));
    setEditingId(null);
  };

  const handleCancelEdit = (e) => {
    e?.stopPropagation();
    setEditingId(null);
  };

  const handleDeleteStep = (id, e) => {
    e?.stopPropagation();
    if (isSubmitted) return;
    setSteps(prev => prev.filter(s => s.id !== id));
  };

  const handleInsertStep = (targetIndex, e) => {
    e?.stopPropagation();
    if (isSubmitted) return;
    const newId = steps.length ? Math.max(...steps.map(s => s.id)) + 1 : 1;
    const newStep = { id: newId, text: 'Новое действие', enabled: true };
    setSteps(prev => {
      const next = [...prev];
      next.splice(targetIndex, 0, newStep);
      return next;
    });
    setEditingId(newId);
    setEditText('Новое действие');
  };

  const handleMoveStep = (idx, direction, e) => {
    e?.stopPropagation();
    if (isSubmitted) return;
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= steps.length) return;
    setSteps(prev => {
      const next = [...prev];
      const temp = next[idx];
      next[idx] = next[targetIdx];
      next[targetIdx] = temp;
      return next;
    });
  };

  const handleAddStep = (e) => {
    handleInsertStep(steps.length, e);
  };

  const handleConfirmPlan = () => {
    if (isSubmitted || isBusy || activeCount === 0) return;
    setIsSubmitted(true);
    setIsCollapsed(true);
    onConfirm?.(planId, steps);
  };

  const handleCancelPlan = () => {
    if (isSubmitted || isBusy) return;
    setIsSubmitted(true);
    onCancel?.(planId);
  };

  // Компактный свернутый вид (для подтвержденных планов и истории)
  if (isSubmitted && isCollapsed) {
    return (
      <div 
        onClick={() => setIsCollapsed(false)}
        className="plan-card plan-collapsed"
        title="Кликните, чтобы развернуть шаги плана"
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <CheckCircle2 size={13} color="var(--accent-success)" />
          <span style={{ fontSize: '11.5px', fontWeight: '500', color: '#cbd5e1' }}>
            План ({formatStepsCount(activeCount)}) утверждён
          </span>
        </div>
        <button 
          type="button"
          className="plan-toggle-btn"
          onClick={(e) => { e.stopPropagation(); setIsCollapsed(false); }}
        >
          <span>Детали</span>
          <ChevronDown size={12} />
        </button>
      </div>
    );
  }

  return (
    <div className="plan-card">
      {/* Шапка плана */}
      <div className="plan-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Sparkles size={13} color="var(--accent-primary)" />
          <span style={{ fontSize: '12px', fontWeight: '600', color: '#f1f5f9' }}>
            План задачи • {formatStepsCount(activeCount)}
          </span>
        </div>
        {isSubmitted ? (
          <button 
            type="button"
            className="plan-toggle-btn"
            onClick={() => setIsCollapsed(true)}
            title="Свернуть блок"
          >
            <span>Свернуть</span>
            <ChevronUp size={12} />
          </button>
        ) : (
          <span style={{ fontSize: '10.5px', color: 'var(--text-faint)' }}>
            Кликните для правки
          </span>
        )}
      </div>

      {/* Список шагов микро-трек */}
      <div className="plan-steps-list">
        {steps.map((step, idx) => {
          const isEditing = editingId === step.id;
          return (
            <React.Fragment key={step.id}>
              {/* Интерактивный микро-разделитель вставки шага перед элементом */}
              {!isSubmitted && (
                <div 
                  className="plan-insert-divider"
                  onClick={(e) => handleInsertStep(idx, e)}
                  title="Вставить шаг сюда"
                >
                  <span className="plan-insert-divider-line" />
                  <span className="plan-insert-divider-btn">
                    <Plus size={9} strokeWidth={3} />
                  </span>
                  <span className="plan-insert-divider-line" />
                </div>
              )}

              <div
                className={`plan-step-item ${step.enabled ? 'enabled' : 'disabled'}`}
              >
                {/* Кастомный микро-чекбокс */}
                <button
                  type="button"
                  className={`plan-step-check ${step.enabled ? 'checked' : ''}`}
                  onClick={(e) => handleToggleStep(step.id, e)}
                  disabled={isSubmitted}
                  title={step.enabled ? 'Отключить шаг' : 'Включить шаг'}
                >
                  {step.enabled && <Check size={10} strokeWidth={3} />}
                </button>

                <span className="plan-step-idx">{idx + 1}.</span>

                {/* Текст шага или поле ввода */}
                {isEditing ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flex: 1 }}>
                    <input
                      type="text"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveEdit(step.id, e);
                        if (e.key === 'Escape') handleCancelEdit(e);
                      }}
                      autoFocus
                      className="plan-edit-input"
                    />
                    <button
                      type="button"
                      onClick={(e) => handleSaveEdit(step.id, e)}
                      className="plan-icon-btn plan-btn-save"
                      title="Сохранить (Enter)"
                    >
                      <Check size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={handleCancelEdit}
                      className="plan-icon-btn plan-btn-cancel"
                      title="Отмена (Esc)"
                    >
                      <X size={13} />
                    </button>
                  </div>
                ) : (
                  <div
                    onClick={(e) => handleStartEdit(step, e)}
                    className="plan-step-text"
                    title={isSubmitted ? '' : 'Кликните для редактирования'}
                  >
                    <span>{step.text}</span>
                    {!isSubmitted && (
                      <div className="plan-step-actions">
                        {/* Кнопка вставки шага прямо после текущего */}
                        <button
                          type="button"
                          onClick={(e) => handleInsertStep(idx + 1, e)}
                          className="plan-icon-btn plan-btn-insert"
                          title="Вставить шаг ниже"
                        >
                          <PlusCircle size={11} />
                        </button>
                        {/* Перемещение шага вверх/вниз */}
                        {idx > 0 && (
                          <button
                            type="button"
                            onClick={(e) => handleMoveStep(idx, -1, e)}
                            className="plan-icon-btn"
                            title="Переместить шаг вверх"
                          >
                            <ArrowUp size={11} />
                          </button>
                        )}
                        {idx < steps.length - 1 && (
                          <button
                            type="button"
                            onClick={(e) => handleMoveStep(idx, 1, e)}
                            className="plan-icon-btn"
                            title="Переместить шаг вниз"
                          >
                            <ArrowDown size={11} />
                          </button>
                        )}
                        <Edit3 size={11} className="plan-action-icon" />
                        <button
                          type="button"
                          onClick={(e) => handleDeleteStep(step.id, e)}
                          className="plan-icon-btn plan-btn-delete"
                          title="Удалить шаг"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </React.Fragment>
          );
        })}
      </div>

      {/* Кнопка добавления шага */}
      {!isSubmitted && (
        <button
          type="button"
          onClick={handleAddStep}
          className="plan-add-step-btn"
        >
          <Plus size={12} />
          Добавить пункт
        </button>
      )}

      {/* Панель подтверждения / отмены */}
      <div className="plan-footer">
        {isSubmitted ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            fontSize: '11.5px',
            color: 'var(--accent-success)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <CheckCircle2 size={13} />
              <span>План утверждён и выполняется</span>
            </div>
            <button 
              type="button"
              className="plan-toggle-btn"
              onClick={() => setIsCollapsed(true)}
            >
              Свернуть
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', width: '100%' }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleConfirmPlan}
              disabled={isBusy || activeCount === 0}
              style={{
                fontSize: '11.5px',
                padding: '4px 10px',
                height: '28px',
                flex: 1
              }}
            >
              <CheckCircle2 size={13} />
              Запустить ({activeCount})
            </button>
            <button
              type="button"
              className="btn"
              onClick={handleCancelPlan}
              disabled={isBusy}
              style={{
                fontSize: '11.5px',
                padding: '4px 10px',
                height: '28px',
                background: 'rgba(255, 255, 255, 0.04)',
                color: 'var(--text-muted)'
              }}
            >
              Отмена
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPanel({
  messages,
  isBusy,
  onSendMessage,
  onClearHistory,
  onConfirmPlan,
  onCancelPlan,
  onOpenDialogs,
  activeSessionTitle
}) {
  const [attachedImage, setAttachedImage] = useState(null);
  const [isAnnotatorOpen, setIsAnnotatorOpen] = useState(false);
  const [viewingImage, setViewingImage] = useState(null);
  const fileInputRef = useRef(null);

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (ev) => {
        setAttachedImage(ev.target.result);
        setIsAnnotatorOpen(true);
      };
      reader.readAsDataURL(file);
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handlePaste = (e) => {
    const items = e.clipboardData?.items;
    if (items) {
      for (let i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.indexOf('image') !== -1) {
          const blob = items[i].getAsFile();
          if (blob) {
            e.preventDefault();
            const reader = new FileReader();
            reader.onload = (ev) => {
              setAttachedImage(ev.target.result);
              setIsAnnotatorOpen(true);
            };
            reader.readAsDataURL(blob);
            break;
          }
        }
      }
    }
  };
  const [inputText, setInputText] = useState('');
  const [replyingTo, setReplyingTo] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isBusy]);

  const adjustTextareaHeight = (el) => {
    if (!el) return;
    el.style.height = 'auto';
    // Максимум 10 строк (~22px строка -> ~220px)
    const maxHeight = 220;
    const newHeight = Math.min(el.scrollHeight, maxHeight);
    el.style.height = `${newHeight}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
  };

  const handleInputChange = (e) => {
    setInputText(e.target.value);
    adjustTextareaHeight(e.target);
  };

  const fallbackCopy = (text, msgId) => {
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
        setCopiedId(msgId);
        setTimeout(() => setCopiedId(null), 2000);
      }
    } catch (err) {
      console.error('Fallback copy failed:', err);
    }
  };

  const handleCopyText = (text, msgId, e) => {
    e?.stopPropagation();
    if (!text) return;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => {
        setCopiedId(msgId);
        setTimeout(() => setCopiedId(null), 2000);
      }).catch(() => {
        fallbackCopy(text, msgId);
      });
    } else {
      fallbackCopy(text, msgId);
    }
  };

  const handleReply = (msg, msgId, e) => {
    e?.stopPropagation();
    setReplyingTo({
      id: msgId,
      role: msg.role,
      text: msg.text || ''
    });
    setTimeout(() => {
      textareaRef.current?.focus();
    }, 50);
  };

  const handleInsertPrompt = (text, e) => {
    e?.stopPropagation();
    setInputText(text);
    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        adjustTextareaHeight(textareaRef.current);
      }
    }, 50);
  };

  const handleSubmit = (e) => {
    e?.preventDefault();
    let text = inputText.trim();
    if ((!text && !attachedImage) || isBusy) return;
    if (!text && attachedImage) text = "Посмотри прикреплённый скриншот с пометками";

    let fullMessage = text;
    if (replyingTo) {
      const quoteSnippet = replyingTo.text.length > 80 
        ? replyingTo.text.slice(0, 80).trim() + '...' 
        : replyingTo.text.trim();
      const authorLabel = replyingTo.role === 'user' ? 'на команду' : 'агенту';
      fullMessage = `[В ответ ${authorLabel}: "${quoteSnippet}"]\n${text}`;
      setReplyingTo(null);
    }

    onSendMessage(fullMessage, attachedImage);
    setInputText('');
    setAttachedImage(null);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Рендеринг текста сообщения с кликабельными ссылками и безопасным переносом
  const renderMessageContent = (msg, msgIndex) => {
    let text = msg.text || '';
    const metadata = msg.metadata || {};

    // Если это сообщение плана, удаляем из текста сырой дублирующий список шагов
    if (metadata.type === 'plan_confirmation') {
      const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
      text = lines[0] || 'Уточните план задачи перед началом:';
    }

    // Извлечение ссылок (URL)
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    const parts = text.split(urlRegex);

    return (
      <div className="chat-selectable-text">
        <div style={{
          wordBreak: 'break-word',
          overflowWrap: 'anywhere',
          whiteSpace: 'pre-wrap',
          lineHeight: '1.4',
          fontSize: '12.5px',
          userSelect: 'text',
          WebkitUserSelect: 'text'
        }}>
          {parts.map((part, i) => {
            if (part.match(urlRegex)) {
              return (
                <a
                  key={i}
                  href={part}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    color: '#38bdf8',
                    textDecoration: 'underline',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontWeight: '500',
                    margin: '2px 0',
                    wordBreak: 'break-all'
                  }}
                >
                  {part}
                  <ExternalLink size={12} />
                </a>
              );
            }
            return part;
          })}
        </div>

        {/* Прикрепленное изображение в сообщении */}
        {metadata.image && (
          <div style={{ marginTop: '8px', marginBottom: '6px' }}>
            <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%' }}>
              <img
                src={metadata.image}
                alt="Прикреплённый скриншот"
                onClick={() => setViewingImage(metadata.image)}
                style={{
                  maxWidth: '100%',
                  maxHeight: '260px',
                  borderRadius: '8px',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  cursor: 'zoom-in',
                  display: 'block',
                  objectFit: 'contain',
                  background: 'rgba(0, 0, 0, 0.25)'
                }}
              />
              <button
                type="button"
                onClick={() => setViewingImage(metadata.image)}
                style={{
                  position: 'absolute',
                  top: '6px',
                  right: '6px',
                  background: 'rgba(0, 0, 0, 0.65)',
                  border: 'none',
                  borderRadius: '4px',
                  color: '#fff',
                  padding: '3px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                title="Увеличить"
              >
                <Maximize2 size={12} />
              </button>
            </div>
          </div>
        )}

        {/* Интерактивное согласование плана составной задачи */}
        {metadata.type === 'plan_confirmation' && (() => {
          const isHistorical = typeof msgIndex === 'number' && messages.slice(msgIndex + 1).some(
            m => m.text?.includes('План утверждён') || m.text?.includes('утвержден') || m.metadata?.type === 'plan_confirmation' || m.role === 'user'
          );
          return (
            <PlanConfirmationCard
              planId={metadata.plan_id}
              initialSteps={metadata.steps || []}
              onConfirm={onConfirmPlan}
              onCancel={onCancelPlan}
              isBusy={isBusy}
              isHistorical={isHistorical}
            />
          );
        })()}

        {/* Интерактивные кнопки подтверждения публикации */}
        {metadata.type === 'publish_prompt' && (() => {
          const isHistorical = typeof msgIndex === 'number' && messages.slice(msgIndex + 1).some(
            m => m.role === 'user' || m.text?.includes('опублик') || m.text?.includes('черновик')
          );
          if (isHistorical) return null;
          return (
            <div style={{ marginTop: '10px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button
                className="btn btn-success"
                style={{ fontSize: '12px', padding: '6px 12px' }}
                onClick={() => onSendMessage('Да, опубликуй')}
              >
                <CheckCircle2 size={13} />
                Да, опубликовать
              </button>
              <button
                className="btn"
                style={{ fontSize: '12px', padding: '6px 12px' }}
                onClick={() => onSendMessage('Нет, оставь черновик')}
              >
                Оставить в черновике
              </button>
            </div>
          );
        })()}

        {/* Плашка ссылки на опубликованный сайт */}
        {metadata.url && (
          <div style={{
            marginTop: '10px',
            padding: '8px 12px',
            background: 'rgba(16, 185, 129, 0.12)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            borderRadius: 'var(--radius-sm)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px',
            flexWrap: 'wrap'
          }}>
            <span style={{ fontSize: '12px', color: '#6ee7b7' }}>Сайт доступен в сети:</span>
            <a
              href={metadata.url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-success"
              style={{ padding: '4px 10px', fontSize: '12px', textDecoration: 'none' }}
            >
              Открыть сайт
              <ExternalLink size={12} />
            </a>
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border-subtle)',
      position: 'relative'
    }}>
      {/* Шапка чата */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'rgba(17, 23, 38, 0.5)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <button
            type="button"
            className="btn btn-icon"
            onClick={onOpenDialogs}
            title="Список диалогов и логинов Tilda"
            style={{ padding: '4px', color: 'var(--accent-primary)', flexShrink: 0 }}
          >
            <MessageSquare size={16} />
          </button>
          <span style={{
            fontWeight: '600',
            fontSize: '13.5px',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis'
          }}>
            {activeSessionTitle || 'Интеллектуальный диалог'}
          </span>
          <span style={{
            fontSize: '11px',
            background: 'rgba(255, 255, 255, 0.06)',
            padding: '2px 6px',
            borderRadius: '10px',
            color: 'var(--text-muted)',
            flexShrink: 0
          }}>
            {messages.length}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-icon"
            onClick={onOpenDialogs}
            title="Управление диалогами"
            style={{ padding: '6px', color: 'var(--text-muted)' }}
          >
            <MessageSquare size={14} />
          </button>
          {messages.length > 0 && (
            <button
              className="btn btn-icon"
              onClick={onClearHistory}
              title="Очистить историю диалога"
              style={{ padding: '6px', color: 'var(--text-faint)' }}
            >
              <Trash2 size={15} />
            </button>
          )}
        </div>
      </div>

      {/* Лента сообщений */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px'
      }}>
        {messages.length === 0 ? (
          <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-muted)',
            textAlign: 'center',
            padding: '20px'
          }}>
            <div style={{
              width: '48px',
              height: '48px',
              borderRadius: '50%',
              background: 'rgba(99, 102, 241, 0.1)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '12px'
            }}>
              <Sparkles size={24} color="var(--accent-primary)" />
            </div>
            <div style={{ fontWeight: '600', fontSize: '15px', color: 'var(--text-main)', marginBottom: '6px' }}>
              mdAgent готов к выполнению задач
            </div>
            <div style={{ fontSize: '12px', maxWidth: '280px', lineHeight: '1.5' }}>
              Задайте команду на естественном языке, например: «Создай страницу лендинга» или «Очисти все блоки».
            </div>
          </div>
        ) : (
          messages.map((msg, index) => {
            const isUser = msg.role === 'user';
            const isError = msg.metadata?.is_error;
            const msgId = msg.id || `msg-${index}`;
            const isCopied = copiedId === msgId;

            return (
              <div
                key={msgId}
                className={`chat-message-row ${isUser ? 'user' : 'agent'}`}
              >
                {!isUser && (
                  <div style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '8px',
                    background: isError ? 'rgba(239, 68, 68, 0.2)' : 'rgba(99, 102, 241, 0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    marginTop: '2px',
                    userSelect: 'none'
                  }}>
                    {isError ? (
                      <AlertCircle size={15} color="var(--accent-danger)" />
                    ) : (
                      <Bot size={15} color="var(--accent-primary)" />
                    )}
                  </div>
                )}

                <div 
                  className="chat-bubble-container"
                  style={{
                    padding: '10px 14px',
                    borderRadius: isUser ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                    background: isUser
                      ? 'linear-gradient(135deg, var(--accent-primary), var(--accent-primary-hover))'
                      : isError 
                        ? 'rgba(239, 68, 68, 0.1)' 
                        : 'var(--bg-surface-elevated)',
                    border: isError
                      ? '1px solid rgba(239, 68, 68, 0.3)'
                      : isUser 
                        ? 'none' 
                        : '1px solid var(--border-subtle)',
                    color: 'var(--text-main)',
                    boxShadow: 'var(--shadow-sm)',
                    wordBreak: 'break-word',
                    overflowWrap: 'anywhere'
                  }}
                >
                  {/* Плавающая панель действий при наведении на сообщение */}
                  <div className="chat-msg-actions">
                    <button
                      type="button"
                      className={`chat-msg-action-btn ${isCopied ? 'success' : ''}`}
                      onClick={(e) => handleCopyText(msg.text, msgId, e)}
                      title={isCopied ? 'Скопировано!' : 'Скопировать текст'}
                    >
                      {isCopied ? <Check size={12} /> : <Copy size={12} />}
                    </button>
                    <button
                      type="button"
                      className="chat-msg-action-btn"
                      onClick={(e) => handleReply(msg, msgId, e)}
                      title="Ответить / Цитировать"
                    >
                      <CornerUpLeft size={12} />
                    </button>
                    {isUser && (
                      <button
                        type="button"
                        className="chat-msg-action-btn"
                        onClick={(e) => handleInsertPrompt(msg.text, e)}
                        title="Повторить команду в поле ввода"
                      >
                        <ArrowDownLeft size={12} />
                      </button>
                    )}
                  </div>

                  <div className="chat-selectable-text">
                    {renderMessageContent(msg, index)}
                  </div>

                  <div 
                    className="no-select chat-msg-time"
                    style={{
                      fontSize: '10px',
                      color: isUser ? 'rgba(255, 255, 255, 0.7)' : 'var(--text-faint)',
                      marginTop: '4px',
                      textAlign: isUser ? 'right' : 'left'
                    }}
                  >
                    {msg.time_str || (msg.timestamp ? new Date(msg.timestamp * 1000).toLocaleTimeString() : '')}
                  </div>
                </div>

                {isUser && (
                  <div style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '8px',
                    background: 'rgba(255, 255, 255, 0.1)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    marginTop: '2px',
                    userSelect: 'none'
                  }}>
                    <User size={15} color="#fff" />
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Анимация "Агент думает" */}
        {isBusy && (
          <div style={{ display: 'flex', gap: '10px', alignSelf: 'flex-start', alignItems: 'center' }}>
            <div style={{
              width: '28px',
              height: '28px',
              borderRadius: '8px',
              background: 'rgba(99, 102, 241, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Bot size={15} color="var(--accent-primary)" />
            </div>
            <div style={{
              padding: '8px 14px',
              borderRadius: '14px 14px 14px 2px',
              background: 'var(--bg-surface-elevated)',
              border: '1px solid var(--border-subtle)',
              fontSize: '12px',
              color: 'var(--text-muted)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              <span className="live-dot" style={{ width: '6px', height: '6px', background: 'var(--accent-primary)' }} />
              mdAgent выполняет действие...
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Поле ввода с плашкой цитирования над ним */}
      <div style={{
        padding: '12px 16px',
        borderTop: '1px solid var(--border-subtle)',
        background: 'rgba(17, 23, 38, 0.95)'
      }}>
        {/* Плашка цитирования при ответе */}
        {replyingTo && (
          <div className="chat-reply-banner">
            <div className="chat-reply-content">
              <CornerUpLeft size={13} color="var(--accent-primary)" style={{ flexShrink: 0 }} />
              <div className="chat-reply-info">
                <span className="chat-reply-author">
                  {replyingTo.role === 'user' ? 'Ответ на вашу команду' : 'Ответ агенту (mdAgent)'}
                </span>
                <span className="chat-reply-text">
                  {replyingTo.text}
                </span>
              </div>
            </div>
            <button
              type="button"
              className="chat-reply-close"
              onClick={() => setReplyingTo(null)}
              title="Отменить цитирование"
            >
              <X size={13} />
            </button>
          </div>
        )}

        {/* Превью прикрепленного изображения */}
        {attachedImage && (
          <div className="chat-attached-image-bar">
            <div 
              className="chat-attached-thumb-wrapper" 
              onClick={() => setIsAnnotatorOpen(true)}
              title="Кликните для рисования и разметки скриншота"
            >
              <img src={attachedImage} alt="Скриншот" className="chat-attached-thumb" />
              <div className="chat-attached-draw-badge">
                <Pen size={11} />
                <span>Нарисовать</span>
              </div>
            </div>
            <div className="chat-attached-info">
              <span className="chat-attached-title">Скриншот прикреплен</span>
              <span className="chat-attached-hint">Нажмите на изображение для выбора цвета, жирности и рисования</span>
            </div>
            <button
              type="button"
              className="chat-attached-remove-btn"
              onClick={() => setAttachedImage(null)}
              title="Удалить скриншот"
            >
              <X size={13} />
            </button>
          </div>
        )}

        <form 
          onSubmit={handleSubmit} 
          style={{ 
            display: 'flex', 
            alignItems: 'flex-end', 
            gap: '8px',
            background: 'var(--bg-base)',
            borderRadius: 'var(--radius-md)',
            padding: '6px 10px',
            border: '1px solid rgba(255, 255, 255, 0.05)'
          }}
        >
          <button
            type="button"
            className="btn btn-icon"
            onClick={() => fileInputRef.current?.click()}
            title="Прикрепить фото / скриншот (или вставьте через Ctrl+V)"
            style={{ padding: '6px', color: attachedImage ? 'var(--accent-primary)' : 'var(--text-muted)', height: '32px' }}
          >
            <Paperclip size={15} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={handleFileSelect}
          />
          <textarea
            ref={textareaRef}
            onPaste={handlePaste}
            rows={1}
            value={inputText}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={isBusy ? 'Агент выполняет задачу...' : 'Введите команду...'}
            disabled={isBusy}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              boxShadow: 'none',
              color: 'var(--text-main)',
              fontSize: '13px',
              lineHeight: '1.4',
              padding: '6px 4px',
              resize: 'none',
              fontFamily: 'inherit',
              minHeight: '28px',
              maxHeight: '220px',
              overflowY: 'hidden'
            }}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!inputText.trim() || isBusy}
            style={{ 
              padding: '7px 12px', 
              borderRadius: 'var(--radius-sm)', 
              height: '32px',
              flexShrink: 0,
              outline: 'none',
              boxShadow: 'none'
            }}
          >
            <Send size={14} />
          </button>
        </form>
      </div>

      {/* Модалка аннотации и рисования на скриншоте */}
      <ImageAnnotatorModal
        isOpen={isAnnotatorOpen}
        imageSrc={attachedImage}
        onSave={(annotated) => {
          setAttachedImage(annotated);
          setIsAnnotatorOpen(false);
        }}
        onClose={() => setIsAnnotatorOpen(false)}
      />

      {/* Полноэкранный просмотр скриншота */}
      {viewingImage && (
        <div className="image-viewer-overlay" onClick={() => setViewingImage(null)}>
          <div className="image-viewer-modal" onClick={(e) => e.stopPropagation()}>
            <img src={viewingImage} alt="Скриншот" className="image-viewer-img" />
            <button
              type="button"
              className="image-viewer-close"
              onClick={() => setViewingImage(null)}
              title="Закрыть (Esc)"
            >
              <X size={18} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
