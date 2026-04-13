import { useState } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

function DragHandle() {
  return (
    <div className="cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600 select-none px-1">
      <svg width="12" height="20" viewBox="0 0 12 20" fill="currentColor">
        <circle cx="4" cy="4" r="1.5" /><circle cx="8" cy="4" r="1.5" />
        <circle cx="4" cy="10" r="1.5" /><circle cx="8" cy="10" r="1.5" />
        <circle cx="4" cy="16" r="1.5" /><circle cx="8" cy="16" r="1.5" />
      </svg>
    </div>
  );
}

function SortableLevel({ level, index, pracownicy, onChange, onDelete }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: level._key });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className={`border rounded-lg p-4 bg-white ${isDragging ? 'shadow-lg' : ''} ${level.opcjonalny ? 'border-dashed border-gray-400' : 'border-gray-200'}`}>
      <div className="flex items-start gap-3">
        <div {...attributes} {...listeners}>
          <DragHandle />
        </div>
        <div className="flex-1 grid grid-cols-2 gap-3">
          <div>
            <label className="form-label text-xs">Nazwa etapu</label>
            <input
              type="text"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
              value={level.nazwa || ''}
              onChange={e => onChange(index, 'nazwa', e.target.value)}
              placeholder={`Etap ${index + 1}`}
            />
          </div>
          <div>
            <label className="form-label text-xs">Zatwierdzający *</label>
            <select
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
              value={level.zatwierdzajacy_id || ''}
              onChange={e => onChange(index, 'zatwierdzajacy_id', e.target.value ? parseInt(e.target.value) : '')}
            >
              <option value="">-- Wybierz osobę --</option>
              {pracownicy.map(p => (
                <option key={p.id} value={p.id}>{p.imie} {p.nazwisko} ({p.stanowisko || '—'})</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={level.opcjonalny || false}
                onChange={e => onChange(index, 'opcjonalny', e.target.checked)}
                className="rounded border-gray-300 text-primary-600"
              />
              Opcjonalny
            </label>
          </div>
          {level.opcjonalny && (
            <div>
              <label className="form-label text-xs">Warunek pominięcia</label>
              <input
                type="text"
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
                value={level.opis_warunku_pominiecia || ''}
                onChange={e => onChange(index, 'opis_warunku_pominiecia', e.target.value)}
                placeholder="Kiedy można pominąć..."
              />
            </div>
          )}
          <div>
            <label className="form-label text-xs">Przypomnienie po (dni)</label>
            <input
              type="number"
              min={1}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
              value={level.przypomnienie_dni ?? 3}
              onChange={e => onChange(index, 'przypomnienie_dni', parseInt(e.target.value) || 3)}
            />
          </div>
          <div>
            <label className="form-label text-xs">Eskalacja po (dni)</label>
            <input
              type="number"
              min={1}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
              value={level.eskalacja_dni ?? 7}
              onChange={e => onChange(index, 'eskalacja_dni', parseInt(e.target.value) || 7)}
            />
          </div>
        </div>
        <button onClick={() => onDelete(index)} className="text-red-400 hover:text-red-600 mt-1 flex-shrink-0">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </div>
    </div>
  );
}

export default function WorkflowDndEditor({ levels, onChange, pracownicy = [] }) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  function handleDragEnd(event) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = levels.findIndex(l => l._key === active.id);
    const newIndex = levels.findIndex(l => l._key === over.id);
    const reordered = arrayMove(levels, oldIndex, newIndex).map((l, i) => ({ ...l, kolejnosc: i + 1 }));
    onChange(reordered);
  }

  const updateLevel = (i, field, val) => {
    const updated = [...levels];
    updated[i] = { ...updated[i], [field]: val };
    onChange(updated);
  };

  const deleteLevel = (i) => {
    const updated = levels.filter((_, idx) => idx !== i).map((l, idx) => ({ ...l, kolejnosc: idx + 1 }));
    onChange(updated);
  };

  const addLevel = () => {
    const key = `new_${Date.now()}`;
    onChange([...levels, {
      _key: key,
      kolejnosc: levels.length + 1,
      nazwa: '',
      zatwierdzajacy_id: '',
      opcjonalny: false,
      przypomnienie_dni: 3,
      eskalacja_dni: 7,
    }]);
  };

  return (
    <div className="space-y-3">
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={levels.map(l => l._key)} strategy={verticalListSortingStrategy}>
          {levels.map((level, i) => (
            <SortableLevel
              key={level._key}
              level={level}
              index={i}
              pracownicy={pracownicy}
              onChange={updateLevel}
              onDelete={deleteLevel}
            />
          ))}
        </SortableContext>
      </DndContext>

      {levels.length === 0 && (
        <div className="border-2 border-dashed border-gray-200 rounded-lg py-8 text-center text-sm text-gray-400">
          Brak poziomów. Dodaj co najmniej jeden.
        </div>
      )}

      <button onClick={addLevel} className="btn-secondary w-full">
        + Dodaj poziom
      </button>

      {/* Preview */}
      {levels.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium text-gray-500 mb-2">Podgląd ścieżki:</p>
          <div className="flex items-center gap-2 flex-wrap p-3 bg-gray-50 rounded-lg">
            {levels.map((l, i) => (
              <div key={l._key} className="flex items-center gap-2">
                <div className={`px-2 py-1 rounded text-xs border ${l.opcjonalny ? 'border-dashed border-gray-400 text-gray-500' : 'border-primary-300 bg-primary-50 text-primary-700'}`}>
                  {l.kolejnosc}. {pracownicy.find(p => p.id === l.zatwierdzajacy_id)?.nazwisko || l.nazwa || '?'}
                </div>
                {i < levels.length - 1 && <span className="text-gray-400">→</span>}
              </div>
            ))}
            <span className="text-gray-400">→</span>
            <div className="px-2 py-1 rounded text-xs border border-blue-300 bg-blue-50 text-blue-700">IT</div>
          </div>
        </div>
      )}
    </div>
  );
}
