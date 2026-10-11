import React, { useState, useRef, useEffect, useCallback } from 'react';
import { X, Check, RotateCcw, Trash2, Pen, CircleDot } from 'lucide-react';

const COLORS = [
  { name: 'Красный', value: '#ef4444' },
  { name: 'Желтый', value: '#eab308' },
  { name: 'Зеленый', value: '#10b981' },
  { name: 'Голубой', value: '#38bdf8' },
  { name: 'Белый', value: '#ffffff' },
  { name: 'Черный', value: '#000000' }
];

const STROKE_WIDTHS = [
  { label: 'Тонкая', value: 3 },
  { label: 'Средняя', value: 6 },
  { label: 'Жирная', value: 12 }
];

export default function ImageAnnotatorModal({ isOpen, imageSrc, onSave, onClose }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const originalImageRef = useRef(null);

  const [color, setColor] = useState('#ef4444');
  const [lineWidth, setLineWidth] = useState(6);
  const [isDrawing, setIsDrawing] = useState(false);
  const [history, setHistory] = useState([]); // Array of ImageData snapshots

  // Загрузка изображения на Canvas
  useEffect(() => {
    if (!isOpen || !imageSrc) return;

    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      originalImageRef.current = img;
      const canvas = canvasRef.current;
      if (!canvas) return;

      canvas.width = img.naturalWidth || img.width;
      canvas.height = img.naturalHeight || img.height;

      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0);

      // Сохраняем исходное состояние в стек истории
      const initialData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      setHistory([initialData]);
    };
    img.src = imageSrc;
  }, [isOpen, imageSrc]);

  // Координаты курсора относительно Canvas
  const getCoordinates = (e) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;

    let clientX = e.clientX;
    let clientY = e.clientY;

    if (e.touches && e.touches.length > 0) {
      clientX = e.touches[0].clientX;
      clientY = e.touches[0].clientY;
    }

    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY
    };
  };

  const startDrawing = (e) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const { x, y } = getCoordinates(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;

    setIsDrawing(true);
  };

  const draw = (e) => {
    if (!isDrawing) return;
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const { x, y } = getCoordinates(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  };

  const stopDrawing = (e) => {
    if (!isDrawing) return;
    e.preventDefault();
    setIsDrawing(false);

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.closePath();

    // Сохраняем снимок в историю (до 20 шагов)
    const snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);
    setHistory((prev) => [...prev.slice(-19), snapshot]);
  };

  const handleUndo = () => {
    if (history.length <= 1) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const nextHistory = [...history];
    nextHistory.pop(); // удаляем текущее состояние
    const previousSnapshot = nextHistory[nextHistory.length - 1];

    if (previousSnapshot) {
      ctx.putImageData(previousSnapshot, 0, 0);
      setHistory(nextHistory);
    }
  };

  const handleClear = () => {
    const canvas = canvasRef.current;
    const img = originalImageRef.current;
    if (!canvas || !img) return;
    const ctx = canvas.getContext('2d');

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0);

    const initialData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    setHistory([initialData]);
  };

  const handleSave = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const annotatedBase64 = canvas.toDataURL('image/jpeg', 0.9);
    onSave?.(annotatedBase64);
  };

  // Keyboard shortcut Ctrl+Z and Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose?.();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'я')) {
        e.preventDefault();
        handleUndo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, history]);

  if (!isOpen) return null;

  return (
    <div className="annotator-overlay">
      <div className="annotator-card">
        {/* Шапка модалки */}
        <div className="annotator-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Pen size={18} color="var(--accent-primary)" />
            <span style={{ fontWeight: '600', fontSize: '15px' }}>Разметка скриншота</span>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              (нарисуйте стрелки или выделите нужные элементы)
            </span>
          </div>
          <button
            type="button"
            className="btn btn-icon"
            onClick={onClose}
            title="Закрыть без сохранения"
          >
            <X size={18} />
          </button>
        </div>

        {/* Панель инструментов: цвет и жирность */}
        <div className="annotator-toolbar">
          <div className="annotator-tool-group">
            <span className="annotator-tool-label">Цвет:</span>
            <div style={{ display: 'flex', gap: '6px' }}>
              {COLORS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setColor(c.value)}
                  className={`annotator-color-btn ${color === c.value ? 'active' : ''}`}
                  style={{ background: c.value }}
                  title={c.name}
                />
              ))}
            </div>
          </div>

          <div className="annotator-tool-group">
            <span className="annotator-tool-label">Жирность:</span>
            <div style={{ display: 'flex', gap: '4px' }}>
              {STROKE_WIDTHS.map((sw) => (
                <button
                  key={sw.value}
                  type="button"
                  onClick={() => setLineWidth(sw.value)}
                  className={`annotator-btn-size ${lineWidth === sw.value ? 'active' : ''}`}
                  title={`${sw.label} (${sw.value}px)`}
                >
                  <span
                    style={{
                      display: 'inline-block',
                      width: `${Math.max(4, sw.value)}px`,
                      height: `${Math.max(4, sw.value)}px`,
                      borderRadius: '50%',
                      background: color
                    }}
                  />
                  <span>{sw.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', marginLeft: 'auto' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleUndo}
              disabled={history.length <= 1}
              style={{ padding: '6px 12px', fontSize: '12px', gap: '6px' }}
              title="Отменить последний штрих (Ctrl+Z)"
            >
              <RotateCcw size={14} />
              <span>Отмена</span>
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleClear}
              style={{ padding: '6px 12px', fontSize: '12px', gap: '6px' }}
              title="Сбросить все рисунки"
            >
              <Trash2 size={14} />
              <span>Очистить</span>
            </button>
          </div>
        </div>

        {/* Холст с изображением */}
        <div ref={containerRef} className="annotator-canvas-container">
          <canvas
            ref={canvasRef}
            className="annotator-canvas"
            onMouseDown={startDrawing}
            onMouseMove={draw}
            onMouseUp={stopDrawing}
            onMouseLeave={stopDrawing}
            onTouchStart={startDrawing}
            onTouchMove={draw}
            onTouchEnd={stopDrawing}
          />
        </div>

        {/* Подвал с кнопками */}
        <div className="annotator-footer">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            style={{ padding: '8px 16px', fontSize: '13px' }}
          >
            Отмена
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSave}
            style={{ padding: '8px 18px', fontSize: '13px', gap: '6px' }}
          >
            <Check size={15} />
            Готово (прикрепить к сообщению)
          </button>
        </div>
      </div>
    </div>
  );
}
