import { LogOut, Radio } from 'lucide-react';

const STATUS_LABELS = {
  online: 'Backend Online',
  offline: 'Backend Offline',
  unauthorized: 'Login Required',
  checking: 'Checking Backend',
};

/**
 * Brand, backend status and the live-updates indicator.
 * "Polling" tells the operator that new incidents may lag by up to 10 s.
 */
export default function Topbar({ status, live, canSignOut, onSignOut }) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-shield" aria-hidden="true">PC</span>
        <div>
          <p>Project Chanakya</p>
          <h1>AI Surveillance Command Dashboard</h1>
        </div>
      </div>
      <div className="topbar-status">
        {status === 'online' && (
          <span className={live ? 'stream-pill live' : 'stream-pill'} title={live ? 'Receiving live events' : 'Event stream down - polling instead'}>
            <Radio size={14} aria-hidden="true" />
            {live ? 'Live' : 'Polling'}
          </span>
        )}
        <div className={`backend-status ${status}`} role="status">
          <span aria-hidden="true" />
          {STATUS_LABELS[status] ?? STATUS_LABELS.checking}
        </div>
        {canSignOut && (
          <button type="button" className="btn ghost" onClick={onSignOut}>
            <LogOut size={16} aria-hidden="true" />
            Sign out
          </button>
        )}
      </div>
    </header>
  );
}
