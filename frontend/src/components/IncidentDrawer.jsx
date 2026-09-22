import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Download, ImageOff, LoaderCircle, Undo2, VideoOff, X } from 'lucide-react';
import { apiFetch, isAbortError, mediaUrl } from '../api/client.js';
import { useMountedRef } from '../hooks/useMountedRef.js';
import { cameraName, formatDateTime, incidentTitle, parseTimestamp } from '../lib/format.js';
import { ThreatBadge, ZoneBadge } from './Badges.jsx';

/** The recorder needs pre-roll + post-roll + encoding; after this long a missing clip will not appear. */
const CLIP_GRACE_MS = 60_000;
const CLIP_POLL_MS = 5000;
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])';

function isClipPending(incident, now) {
  if (incident.clip_url) return false;
  const recordedAt = parseTimestamp(incident.timestamp);
  return recordedAt !== null && now - recordedAt < CLIP_GRACE_MS;
}

function Snapshot({ incident }) {
  const [failed, setFailed] = useState(false);
  if (!incident.snapshot_url || failed) {
    return (
      <div className="media-placeholder">
        <ImageOff size={20} aria-hidden="true" />
        <span>{failed ? 'Snapshot unavailable' : 'No snapshot was saved'}</span>
      </div>
    );
  }
  return (
    <>
      <img
        className="drawer-media"
        src={mediaUrl(incident.snapshot_url)}
        alt={`Snapshot of incident ${incident.id}`}
        onError={() => setFailed(true)}
      />
      <a className="btn ghost" href={mediaUrl(`${incident.snapshot_url}?download=1`)} download>
        <Download size={16} aria-hidden="true" />
        Download snapshot
      </a>
    </>
  );
}

function Clip({ incident, pending }) {
  if (incident.clip_url) {
    return (
      <>
        <video className="drawer-media" controls preload="metadata" src={mediaUrl(incident.clip_url)}>
          Your browser cannot play this clip; use the download link instead.
        </video>
        <a className="btn ghost" href={mediaUrl(`${incident.clip_url}?download=1`)} download>
          <Download size={16} aria-hidden="true" />
          Download clip
        </a>
      </>
    );
  }
  if (pending) {
    return (
      <div className="media-placeholder" role="status">
        <LoaderCircle size={20} className="spin" aria-hidden="true" />
        <span>clip processing…</span>
      </div>
    );
  }
  return (
    <div className="media-placeholder">
      <VideoOff size={20} aria-hidden="true" />
      <span>No clip was recorded</span>
    </div>
  );
}

function Detail({ label, children }) {
  return (
    <div className="kv-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * Modal side panel with everything known about one incident.
 *
 * The row that opened it may be stale (a clip is attached seconds after the alert), so the
 * drawer ALWAYS re-fetches the incident on open, listens for `incident_updated` / `ack`,
 * and - as a fallback for when the event stream is down - polls while the clip is pending.
 *
 * Accessibility: focus moves into the dialog on open, Tab is trapped inside it, Escape
 * closes it and focus returns to the element that opened it.
 *
 * @param {{incident: object, cameras: object[], subscribe: Function, emit: Function,
 *          onClose: () => void, onError: (message: string) => void}} props
 */
export default function IncidentDrawer({ incident, cameras, subscribe, emit, onClose, onError }) {
  const [detail, setDetail] = useState(incident);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const panelRef = useRef(null);
  const closeRef = useRef(null);
  const mountedRef = useMountedRef();
  const { id } = incident;
  const pending = isClipPending(detail, now);

  const fetchDetail = useCallback(
    async (signal) => {
      try {
        const fresh = await apiFetch(`/api/incidents/${id}`, { signal });
        if (!signal.aborted && fresh) setDetail(fresh);
      } catch (error) {
        if (!isAbortError(error) && !signal.aborted) onError(`Could not refresh incident ${id}: ${error.message}`);
      }
    },
    [id, onError],
  );

  useEffect(() => {
    // Re-fetch on open so a row that arrived over SSE picks up its clip_url / ack state.
    // Scheduled as a microtask: the state update happens after the effect body returns.
    const controller = new AbortController();
    queueMicrotask(() => fetchDetail(controller.signal));
    return () => controller.abort();
  }, [fetchDetail]);

  useEffect(() => {
    if (!pending) return undefined;
    const controller = new AbortController();
    const intervalId = window.setInterval(() => {
      setNow(Date.now());
      fetchDetail(controller.signal);
    }, CLIP_POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [pending, fetchDetail]);

  useEffect(
    () =>
      subscribe((type, payload) => {
        if (payload?.id !== id) return;
        if (type === 'incident_updated') setDetail(payload);
        else if (type === 'ack') setDetail((prev) => ({ ...prev, acknowledged: Boolean(payload.acknowledged) }));
      }),
    [subscribe, id],
  );

  // Focus management + scroll lock for the modal's lifetime.
  useEffect(() => {
    const opener = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const trapFocus = (event) => {
    if (event.key !== 'Tab' || !panelRef.current) return;
    const focusable = [...panelRef.current.querySelectorAll(FOCUSABLE)];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const toggleAcknowledged = async () => {
    setBusy(true);
    try {
      const updated = await apiFetch(`/api/incidents/${id}/ack`, {
        method: 'POST',
        body: { acknowledged: !detail.acknowledged },
      });
      if (!mountedRef.current) return;
      if (updated) {
        setDetail(updated);
        emit('incident_updated', updated);
      }
    } catch (error) {
      if (mountedRef.current) onError(`Could not update incident ${id}: ${error.message}`);
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  };

  const reasons = Array.isArray(detail.reasons) ? detail.reasons : [];
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        ref={panelRef}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={trapFocus}
      >
        <header className="drawer-header">
          <div>
            <p className="eyebrow">Incident #{id}</p>
            <h2 id="drawer-title">{incidentTitle(detail)}</h2>
          </div>
          <button type="button" className="icon-button" aria-label="Close incident details" ref={closeRef} onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <div className="drawer-body">
          <div className="drawer-badges">
            <ThreatBadge score={detail.threat_score} category={detail.category} />
            <ZoneBadge level={detail.zone_level} />
            <span className={detail.acknowledged ? 'ack-state done' : 'ack-state'}>
              {detail.acknowledged ? 'Acknowledged' : 'Open'}
            </span>
          </div>

          <section aria-label="Snapshot" className="drawer-section">
            <h3>Snapshot</h3>
            <Snapshot incident={detail} />
          </section>

          <section aria-label="Video clip" className="drawer-section">
            <h3>Clip</h3>
            <Clip incident={detail} pending={pending} />
          </section>

          <section aria-label="Threat reasons" className="drawer-section">
            <h3>Why it was flagged</h3>
            {reasons.length > 0 ? (
              <ul className="chips">
                {reasons.map((reason, index) => (
                  <li key={`${reason}-${index}`}>{reason}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">No reasons were recorded.</p>
            )}
          </section>

          <section aria-label="Details" className="drawer-section">
            <h3>Details</h3>
            <dl className="kv-list flush">
              <Detail label="Time">
                <time dateTime={detail.timestamp}>{formatDateTime(detail.timestamp)}</time>
              </Detail>
              <Detail label="Camera">{cameraName(cameras, detail.camera)}</Detail>
              <Detail label="Object">{detail.object_type || 'Unknown'}</Detail>
              <Detail label="Identity">{detail.identity || 'Unknown'}</Detail>
              <Detail label="Emotion">{detail.emotion || 'N/A'}</Detail>
              <Detail label="Track">{detail.track_id ?? 'N/A'}</Detail>
            </dl>
          </section>
        </div>

        <footer className="drawer-footer">
          <button type="button" className={detail.acknowledged ? 'btn ghost' : 'btn primary'} onClick={toggleAcknowledged} disabled={busy}>
            {detail.acknowledged ? <Undo2 size={16} aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}
            {detail.acknowledged ? 'Mark as open' : 'Acknowledge'}
          </button>
        </footer>
      </aside>
    </div>
  );
}
