import { useState } from 'react';
import { Bell, BellOff } from 'lucide-react';
import { apiFetch } from '../api/client.js';
import { useMountedRef } from '../hooks/useMountedRef.js';

/**
 * Pause / resume outbound alert notifications.
 * Pausing silences the notifier (Telegram) only: incidents are still detected, logged and
 * shown here, which the helper text spells out so nobody mistakes it for "detection off".
 */
export default function AlertControls({ paused, onChange, onError }) {
  const [busy, setBusy] = useState(false);
  const mountedRef = useMountedRef();

  const toggle = async () => {
    setBusy(true);
    try {
      const body = await apiFetch(paused ? '/api/alerts/resume' : '/api/alerts/pause', { method: 'POST' });
      if (mountedRef.current) onChange(Boolean(body?.paused));
    } catch (error) {
      if (mountedRef.current) onError(`Could not ${paused ? 'resume' : 'pause'} alerts: ${error.message}`);
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  };

  const Icon = paused ? BellOff : Bell;
  return (
    <div className="alert-controls">
      <button
        type="button"
        className={paused ? 'btn warn' : 'btn'}
        onClick={toggle}
        disabled={busy}
        aria-pressed={paused}
        aria-describedby="alert-controls-hint"
      >
        <Icon size={16} aria-hidden="true" />
        {paused ? 'Resume notifications' : 'Pause notifications'}
      </button>
      <small id="alert-controls-hint">
        {paused
          ? 'Notifications are paused. Incidents are still detected and logged.'
          : 'Pausing silences Telegram only; detection and logging continue.'}
      </small>
    </div>
  );
}
