import { useCallback, useEffect, useMemo, useState } from 'react';
import { Info, RefreshCw, RotateCcw, Save, Trash2 } from 'lucide-react';
import { apiFetch, isAbortError, mediaUrl } from '../api/client.js';
import { useMountedRef } from '../hooks/useMountedRef.js';
import { ZONE_LEVELS } from '../lib/format.js';
import { MAX_ZONES, isBigEnough, newZoneId, normaliseRect, sameZones, zoneFromPayload, zoneToPayload } from '../lib/zoneGeometry.js';
import PanelHeader from './PanelHeader.jsx';
import ZoneCanvas from './ZoneCanvas.jsx';

const DEFAULT_SET = 'default';

function setFromResponse(body, cameraId) {
  const table = body?.zones ?? {};
  const raw = table[cameraId] ?? table[DEFAULT_SET] ?? [];
  return raw.map(zoneFromPayload);
}

/**
 * Per-camera zone editor. Zones are normalised rectangles (0..1) so they survive any
 * stream resolution; the backend evaluates them at a person's feet (bottom-centre of the
 * box), which the note below spells out because it is not what people expect.
 * The background is a one-shot still (never the MJPEG stream) to respect the browser's
 * per-origin connection budget.
 */
export default function ZoneEditor({ cameras, subscribe, onError, onSaved }) {
  const cameraOptions = useMemo(() => [{ id: DEFAULT_SET, name: 'Default (all cameras)' }, ...cameras], [cameras]);
  const [cameraId, setCameraId] = useState(DEFAULT_SET);
  const [table, setTableState] = useState({ version: 0, zones: null });
  // Working copy keyed by (camera, table version): when either changes during render the
  // copy is rebuilt from the table unless the operator has unsaved edits for that camera.
  const [work, setWork] = useState({ key: null, zones: [], saved: [] });
  const [selectedId, setSelectedId] = useState(null);
  const [levels, setLevels] = useState(ZONE_LEVELS);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [background, setBackground] = useState(0);
  const [reloadTick, setReloadTick] = useState(0);
  const mountedRef = useMountedRef();

  const setTable = useCallback((update) => {
    setTableState((current) => ({
      version: current.version + 1,
      zones: typeof update === 'function' ? update(current.zones) : update,
    }));
  }, []);

  const workKey = `${cameraId}:${table.version}`;
  if (table.zones && work.key !== workKey) {
    const fresh = setFromResponse({ zones: table.zones }, cameraId);
    const sameCamera = work.key?.startsWith(`${cameraId}:`);
    const keepEdits = sameCamera && work.zones.length > 0 && !sameZones(work.zones, work.saved);
    setWork({ key: workKey, zones: keepEdits ? work.zones : fresh, saved: fresh });
  }
  const { zones, saved } = work;
  const setZones = useCallback((update) => {
    setWork((current) => ({ ...current, zones: typeof update === 'function' ? update(current.zones) : update }));
  }, []);

  const dirty = !sameZones(zones, saved);
  const usesDefault = cameraId !== DEFAULT_SET && !(table.zones?.[cameraId]);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const body = await apiFetch('/api/zones', { signal: controller.signal });
        if (controller.signal.aborted || !body) return;
        setTable(body.zones ?? {});
        setSelectedId(null);
        if (Array.isArray(body.levels) && body.levels.length) setLevels(body.levels);
      } catch (error) {
        if (!isAbortError(error) && !controller.signal.aborted) onError(`Could not load zones: ${error.message}`);
      }
    };
    queueMicrotask(load);
    return () => controller.abort();
  }, [reloadTick, onError, setTable]);

  useEffect(
    () =>
      subscribe((type, payload) => {
        if (type !== 'zones') return;
        if (payload?.camera_id === cameraId || payload?.camera_id === DEFAULT_SET) {
          if (!dirty) setReloadTick((tick) => tick + 1);
        }
      }),
    [subscribe, cameraId, dirty],
  );

  const updateZone = useCallback((id, patch) => {
    setZones((current) => current.map((zone) => (zone.id === id ? { ...zone, ...patch } : zone)));
  }, [setZones]);

  const onCreate = useCallback(
    (rect) => {
      const normalised = normaliseRect(rect);
      if (!isBigEnough(normalised)) return;
      const zone = { id: newZoneId(), name: `Zone ${zones.length + 1}`, level: 'WARNING', rect: normalised };
      setZones((current) => (current.length >= MAX_ZONES ? current : [...current, zone]));
      setSelectedId(zone.id);
    },
    [zones.length, setZones],
  );

  const onDelete = useCallback((id) => {
    setZones((current) => current.filter((zone) => zone.id !== id));
    setSelectedId((current) => (current === id ? null : current));
  }, [setZones]);

  const put = async (payload, successMessage) => {
    setBusy(true);
    setMessage('');
    try {
      const body = await apiFetch(`/api/zones/${encodeURIComponent(cameraId)}`, { method: 'PUT', body: { zones: payload } });
      if (!mountedRef.current) return;
      const fresh = (body?.zones ?? []).map(zoneFromPayload);
      setTable((current) => {
        const next = { ...(current ?? {}) };
        if (payload.length === 0 && cameraId !== DEFAULT_SET) delete next[cameraId];
        else next[cameraId] = body?.zones ?? [];
        return next;
      });
      setWork({ key: null, zones: fresh, saved: fresh }); // rebuilt from the new table on render
      setSelectedId(null);
      setMessage(successMessage);
      onSaved?.(cameraId);
    } catch (error) {
      if (mountedRef.current) setMessage(`Save failed: ${error.message}`);
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  };

  const save = () => put(zones.map(zoneToPayload), 'Zones saved.');
  const resetToDefault = () => put([], 'Camera now uses the default zones.');
  const discard = () => {
    setWork((current) => ({ ...current, zones: current.saved }));
    setSelectedId(null);
    setMessage('');
  };

  const selected = zones.find((zone) => zone.id === selectedId) ?? null;
  const backgroundUrl = cameraId === DEFAULT_SET
    ? (cameras[0] ? mediaUrl(`/api/cameras/${encodeURIComponent(cameras[0].id)}/snapshot.jpg`, { raw: 1, v: background }) : null)
    : mediaUrl(`/api/cameras/${encodeURIComponent(cameraId)}/snapshot.jpg`, { raw: 1, v: background });

  return (
    <section className="panel zone-editor">
      <PanelHeader title="Zones" subtitle="Draw on the frame to add a zone; drag a zone or its handles to adjust it">
        <div className="panel-actions">
          <div className="field inline">
            <label htmlFor="zone-camera">Camera</label>
            <select
              id="zone-camera"
              value={cameraId}
              disabled={busy}
              onChange={(event) => {
                if (dirty && !window.confirm('Discard unsaved zone changes?')) return;
                setCameraId(event.target.value);
                setSelectedId(null);
                setMessage('');
              }}
            >
              {cameraOptions.map((camera) => (
                <option key={camera.id} value={camera.id}>{camera.name}</option>
              ))}
            </select>
          </div>
          <button type="button" className="btn ghost" onClick={() => setBackground((v) => v + 1)}>
            <RefreshCw size={16} aria-hidden="true" />
            Refresh frame
          </button>
        </div>
      </PanelHeader>

      <p className="zone-note">
        <Info size={14} aria-hidden="true" />
        A person is placed in the zone under their <strong>feet</strong> (bottom-centre of the detection box).
        {usesDefault && ' This camera currently uses the default set; saving creates its own.'}
      </p>

      <div className="zone-layout">
        <ZoneCanvas
          zones={zones}
          selectedId={selectedId}
          backgroundUrl={backgroundUrl}
          canAdd={zones.length < MAX_ZONES && !busy}
          onSelect={setSelectedId}
          onChange={(id, rect) => updateZone(id, { rect })}
          onCreate={onCreate}
          onDelete={onDelete}
        />

        <aside className="zone-sidebar" aria-label="Zone list">
          {zones.length === 0 && <p className="muted">No zones. Draw one on the frame.</p>}
          <ul className="plain-list zone-list">
            {zones.map((zone) => (
              <li key={zone.id} className={zone.id === selectedId ? 'zone-item selected' : 'zone-item'}>
                <button type="button" className="zone-item-select" onClick={() => setSelectedId(zone.id)} aria-pressed={zone.id === selectedId}>
                  <span className={`zone-badge zone-${zone.level.toLowerCase()}`}>{zone.level}</span>
                  <span className="zone-item-name">{zone.name || 'Unnamed zone'}</span>
                </button>
              </li>
            ))}
          </ul>

          {selected && (
            <div className="zone-form">
              <div className="field">
                <label htmlFor="zone-name">Name</label>
                <input
                  id="zone-name"
                  value={selected.name}
                  maxLength={40}
                  onChange={(event) => updateZone(selected.id, { name: event.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="zone-level">Level</label>
                <select id="zone-level" value={selected.level} onChange={(event) => updateZone(selected.id, { level: event.target.value })}>
                  {levels.map((level) => (
                    <option key={level} value={level}>{level}</option>
                  ))}
                </select>
              </div>
              <button type="button" className="btn ghost danger" onClick={() => onDelete(selected.id)}>
                <Trash2 size={16} aria-hidden="true" />
                Delete zone
              </button>
            </div>
          )}

          <div className="zone-actions">
            <button type="button" className="btn primary" onClick={save} disabled={busy || !dirty || zones.some((z) => !z.name.trim())}>
              <Save size={16} aria-hidden="true" />
              Save
            </button>
            <button type="button" className="btn ghost" onClick={discard} disabled={busy || !dirty}>
              Discard
            </button>
            {cameraId !== DEFAULT_SET && (
              <button type="button" className="btn ghost" onClick={resetToDefault} disabled={busy || usesDefault}>
                <RotateCcw size={16} aria-hidden="true" />
                Reset to default
              </button>
            )}
          </div>
          {message && <p className={message.startsWith('Save failed') ? 'form-error' : 'form-ok'} role="status">{message}</p>}
          {dirty && !message && <p className="muted small">Unsaved changes</p>}
        </aside>
      </div>
    </section>
  );
}
