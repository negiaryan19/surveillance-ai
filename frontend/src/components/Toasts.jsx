import { useEffect } from 'react';
import { Siren, TriangleAlert, X } from 'lucide-react';

const AUTO_DISMISS_MS = 8000;

function Toast({ toast, onDismiss }) {
  const { id, tone, title, message, action } = toast;

  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(id), AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [id, onDismiss]);

  const Icon = tone === 'critical' ? Siren : TriangleAlert;
  return (
    // role="alert" makes screen readers announce critical incidents immediately.
    <div className={`toast ${tone}`} role={tone === 'critical' ? 'alert' : 'status'}>
      <Icon size={18} aria-hidden="true" />
      <div className="toast-body">
        <strong>{title}</strong>
        {message && <span>{message}</span>}
        {action && (
          <button
            type="button"
            className="link-button"
            onClick={() => {
              action.onClick();
              onDismiss(id);
            }}
          >
            {action.label}
          </button>
        )}
      </div>
      <button type="button" className="icon-button" aria-label="Dismiss notification" onClick={() => onDismiss(id)}>
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * Stack of transient notifications (new CRITICAL incidents, action failures).
 * @param {{toasts: {id: number, tone: 'critical'|'error'|'info', title: string, message?: string,
 *          action?: {label: string, onClick: () => void}}[], onDismiss: (id: number) => void}} props
 */
export default function Toasts({ toasts, onDismiss }) {
  return (
    <div className="toasts" role="region" aria-label="Notifications">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
