import { useCallback, useEffect, useRef, useState } from 'react';
import { mediaUrl } from '../api/client.js';

/** Every server-sent event type the backend publishes (contract section 3.4). */
const EVENT_TYPES = ['incident', 'incident_updated', 'status', 'ack', 'zones', 'faces'];
const MAX_BACKOFF_MS = 10_000;
const HIDDEN_GRACE_MS = 30_000;

function parseEventData(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * One EventSource per browser tab, shared by every consumer through `subscribe`.
 *
 * - Reconnects by hand with exponential backoff (max 10 s). The native retry gives up for
 *   good on a non-200 answer (401 before login, 503 when the subscriber cap is hit), so the
 *   source is always closed and re-created here instead.
 * - Closes the stream once the page has been hidden for 30 s and reopens it when the page
 *   becomes visible again, so background tabs do not hold one of the browser's six
 *   per-origin connections.
 *
 * @param {boolean} enabled false while the backend is offline or login is pending
 * @returns {{connected: boolean,
 *            subscribe: (listener: (type: string, data: object) => void) => () => void,
 *            emit: (type: string, data: object) => void}}
 *   `emit` delivers a local event to the same listeners, letting a component that just
 *   changed something (e.g. acknowledged an incident) update every list immediately even
 *   while the stream is down.
 */
export function useEventStream(enabled) {
  const [connected, setConnected] = useState(false);
  const listenersRef = useRef(null);
  if (listenersRef.current === null) listenersRef.current = new Set();

  const subscribe = useCallback((listener) => {
    const listeners = listenersRef.current;
    listeners.add(listener);
    return () => listeners.delete(listener);
  }, []);

  const emit = useCallback((type, data) => {
    for (const listener of [...listenersRef.current]) {
      try {
        listener(type, data);
      } catch (error) {
        console.error('event listener failed', error);
      }
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    let source = null;
    let retryTimer = null;
    let hideTimer = null;
    let attempt = 0;
    let suspended = false;
    let disposed = false;

    const closeSource = () => {
      if (source) {
        source.close();
        source = null;
      }
    };

    const connect = () => {
      if (disposed || suspended || source) return;
      window.clearTimeout(retryTimer);
      retryTimer = null;

      const current = new EventSource(mediaUrl('/api/events'));
      source = current;
      current.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      current.onerror = () => {
        if (source !== current) return;
        closeSource();
        setConnected(false);
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt);
        attempt += 1;
        retryTimer = window.setTimeout(connect, delay);
      };
      for (const type of EVENT_TYPES) {
        current.addEventListener(type, (event) => {
          const data = parseEventData(event.data);
          if (data !== null) emit(type, data);
        });
      }
    };

    const suspend = () => {
      hideTimer = null;
      suspended = true;
      window.clearTimeout(retryTimer);
      retryTimer = null;
      closeSource();
      setConnected(false);
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        if (hideTimer === null && !suspended) hideTimer = window.setTimeout(suspend, HIDDEN_GRACE_MS);
        return;
      }
      window.clearTimeout(hideTimer);
      hideTimer = null;
      if (suspended) {
        suspended = false;
        attempt = 0;
        connect();
      }
    };

    document.addEventListener('visibilitychange', onVisibilityChange);
    onVisibilityChange();
    connect();

    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.clearTimeout(retryTimer);
      window.clearTimeout(hideTimer);
      closeSource();
      setConnected(false);
    };
  }, [enabled, emit]);

  return { connected: enabled && connected, subscribe, emit };
}
