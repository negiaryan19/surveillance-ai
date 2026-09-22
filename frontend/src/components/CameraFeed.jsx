import { useEffect, useState } from 'react';
import { Activity, Crosshair, Moon } from 'lucide-react';
import { mediaUrl } from '../api/client.js';

const MAX_RETRY_MS = 15_000;

/**
 * Ref callback for the MJPEG <img>. Removing an <img> from the DOM does not reliably abort
 * a multipart stream in every browser; blanking `src` first does, which is what frees the
 * connection slot.
 */
function releaseStreamOnDetach(node) {
  return () => {
    node.src = '';
    node.removeAttribute('src');
  };
}

/**
 * The live MJPEG image. It exists only while its parent decides the stream may be open, so
 * mounting IS connecting and unmounting IS disconnecting. Every mount and every retry gets
 * a fresh cache-buster so the browser never resurrects a dead multipart response.
 */
function LiveStream({ cameraId, label }) {
  const [session] = useState(() => Date.now().toString(36));
  const [attempt, setAttempt] = useState(0);
  const [failures, setFailures] = useState(0);
  const [waiting, setWaiting] = useState(false);

  useEffect(() => {
    if (!waiting) return undefined;
    // Backoff 1 s, 2 s, 4 s ... capped: a 503 (viewer cap) or an offline backend should not be hammered.
    const delay = Math.min(MAX_RETRY_MS, 1000 * 2 ** Math.max(0, failures - 1));
    const timer = window.setTimeout(() => {
      setAttempt((value) => value + 1);
      setWaiting(false);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [waiting, failures]);

  if (waiting) {
    return (
      <div className="feed-fallback" role="status">
        <strong>Feed unavailable</strong>
        <span>Reconnecting... check the camera permission or the backend stream.</span>
      </div>
    );
  }

  return (
    <img
      key={attempt}
      ref={releaseStreamOnDetach}
      src={mediaUrl(`/video_feed/${encodeURIComponent(cameraId)}`, { v: `${session}-${attempt}` })}
      alt={`${label} live surveillance feed`}
      onLoad={() => setFailures(0)}
      onError={() => {
        setFailures((count) => count + 1);
        setWaiting(true);
      }}
    />
  );
}

/**
 * One camera tile: status badges plus the live stream.
 *
 * CONNECTION BUDGET: browsers allow ~6 connections per origin across all tabs. `active` must
 * be true only while the Dashboard tab is showing AND the page is visible; otherwise the
 * stream is unmounted and its connection released.
 *
 * @param {{camera: object, active: boolean}} props
 */
export default function CameraFeed({ camera, active }) {
  const { id, name, online, fps, tracks, night_mode: nightMode, source } = camera;

  return (
    <article className="camera-card" aria-label={`Camera ${name}`}>
      <div className="camera-title">
        <span title={source || undefined}>{name}</span>
        <div className="camera-badges">
          {nightMode && (
            <span className="badge night">
              <Moon size={12} aria-hidden="true" />
              Night
            </span>
          )}
          <span className="badge">
            <Activity size={12} aria-hidden="true" />
            {fps.toFixed(1)} fps
          </span>
          <span className="badge">
            <Crosshair size={12} aria-hidden="true" />
            {tracks} track{tracks === 1 ? '' : 's'}
          </span>
          <span className={online ? 'badge online' : 'badge offline'}>{online ? 'Live' : 'Offline'}</span>
        </div>
      </div>
      <div className="camera-frame">
        {active ? (
          <LiveStream cameraId={id} label={name} />
        ) : (
          <div className="feed-fallback">
            <strong>Stream paused</strong>
            <span>Live video resumes when this view is in the foreground.</span>
          </div>
        )}
      </div>
    </article>
  );
}
