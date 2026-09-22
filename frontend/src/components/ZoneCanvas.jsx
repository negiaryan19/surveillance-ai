import { useRef, useState } from 'react';
import { clamp } from '../lib/format.js';
import { isBigEnough, moveRect, normaliseRect, resizeRect } from '../lib/zoneGeometry.js';

const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
const KEY_STEP = 0.01;
const KEY_STEP_LARGE = 0.05;

function handleStyle(handle, rect) {
  const x = handle.includes('w') ? rect.x1 : handle.includes('e') ? rect.x2 : (rect.x1 + rect.x2) / 2;
  const y = handle.includes('n') ? rect.y1 : handle.includes('s') ? rect.y2 : (rect.y1 + rect.y2) / 2;
  return { left: `${x * 100}%`, top: `${y * 100}%`, cursor: `${handle}-resize` };
}

function rectStyle({ x1, y1, x2, y2 }) {
  const left = Math.min(x1, x2);
  const top = Math.min(y1, y2);
  return { left: `${left * 100}%`, top: `${top * 100}%`, width: `${Math.abs(x2 - x1) * 100}%`, height: `${Math.abs(y2 - y1) * 100}%` };
}

/**
 * The drawing surface: a still frame with the zones laid over it.
 *
 * Pointer events (mouse, touch and pen alike) draw on empty space, move a zone by its body
 * and resize by its eight handles; pointer capture keeps a drag alive when it leaves the
 * frame. Every zone is also focusable: arrow keys move it (Shift = larger step,
 * Alt = resize the bottom-right corner) and Delete removes it, so the whole editor can be
 * driven from the keyboard.
 *
 * @param {{zones: object[], selectedId: string | null, backgroundUrl: string | null, canAdd: boolean,
 *          onSelect: (id: string | null) => void, onChange: (id: string, rect: object) => void,
 *          onCreate: (rect: object) => void, onDelete: (id: string) => void}} props
 */
export default function ZoneCanvas({ zones, selectedId, backgroundUrl, canAdd, onSelect, onChange, onCreate, onDelete }) {
  const surfaceRef = useRef(null);
  const dragRef = useRef(null);
  const [drawing, setDrawing] = useState(null);
  const [backgroundFailed, setBackgroundFailed] = useState(false);

  const toNormalised = (event) => {
    const box = surfaceRef.current.getBoundingClientRect();
    return {
      x: clamp((event.clientX - box.left) / box.width, 0, 1),
      y: clamp((event.clientY - box.top) / box.height, 0, 1),
    };
  };

  const startDrag = (event, drag) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    surfaceRef.current.setPointerCapture(event.pointerId);
    dragRef.current = { ...drag, pointerId: event.pointerId, origin: toNormalised(event) };
  };

  const onSurfacePointerDown = (event) => {
    onSelect(null);
    if (!canAdd) return;
    const point = toNormalised(event);
    startDrag(event, { kind: 'draw', start: point });
    setDrawing({ x1: point.x, y1: point.y, x2: point.x, y2: point.y });
  };

  const onPointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const point = toNormalised(event);
    const dx = point.x - drag.origin.x;
    const dy = point.y - drag.origin.y;
    if (drag.kind === 'draw') {
      setDrawing({ x1: drag.start.x, y1: drag.start.y, x2: point.x, y2: point.y });
    } else if (drag.kind === 'move') {
      onChange(drag.id, moveRect(drag.rect, dx, dy));
    } else if (drag.kind === 'resize') {
      onChange(drag.id, resizeRect(drag.rect, drag.handle, dx, dy));
    }
  };

  const endDrag = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (surfaceRef.current.hasPointerCapture(event.pointerId)) surfaceRef.current.releasePointerCapture(event.pointerId);
    if (drag.kind === 'draw') {
      setDrawing((rect) => {
        // A click without a drag is a deselect, not a tiny zone.
        if (rect && isBigEnough(rect)) onCreate(normaliseRect(rect));
        return null;
      });
    }
  };

  const onZoneKeyDown = (event, zone) => {
    const step = event.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
    const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
    if (delta) {
      event.preventDefault();
      const [dx, dy] = delta;
      onChange(zone.id, event.altKey ? resizeRect(zone.rect, 'se', dx, dy) : moveRect(zone.rect, dx, dy));
    } else if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      onDelete(zone.id);
    }
  };

  return (
    <div
      ref={surfaceRef}
      className={canAdd ? 'zone-surface drawable' : 'zone-surface'}
      onPointerDown={onSurfacePointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      {backgroundUrl && !backgroundFailed ? (
        <img src={backgroundUrl} alt="" draggable={false} onError={() => setBackgroundFailed(true)} onLoad={() => setBackgroundFailed(false)} />
      ) : (
        <div className="zone-surface-empty" aria-hidden="true">
          {backgroundUrl ? 'Snapshot unavailable' : 'No camera snapshot'}
        </div>
      )}

      {zones.map((zone, index) => {
        const selected = zone.id === selectedId;
        return (
          <div
            key={zone.id}
            role="button"
            tabIndex={0}
            className={`zone-rect level-${zone.level.toLowerCase()}${selected ? ' selected' : ''}`}
            style={rectStyle(zone.rect)}
            aria-label={`${zone.name}, ${zone.level} zone ${index + 1} of ${zones.length}. Arrow keys move, Alt with arrows resizes, Delete removes.`}
            aria-pressed={selected}
            onFocus={() => onSelect(zone.id)}
            onKeyDown={(event) => onZoneKeyDown(event, zone)}
            onPointerDown={(event) => {
              onSelect(zone.id);
              startDrag(event, { kind: 'move', id: zone.id, rect: zone.rect });
            }}
          >
            <span className="zone-label">{zone.name}</span>
            {selected &&
              HANDLES.map((handle) => (
                <span
                  key={handle}
                  className="zone-handle"
                  style={handleStyle(handle, { x1: 0, y1: 0, x2: 1, y2: 1 })}
                  data-handle={handle}
                  onPointerDown={(event) => startDrag(event, { kind: 'resize', id: zone.id, rect: zone.rect, handle })}
                />
              ))}
          </div>
        );
      })}

      {drawing && <div className="zone-rect drawing" style={rectStyle(drawing)} aria-hidden="true" />}
    </div>
  );
}
