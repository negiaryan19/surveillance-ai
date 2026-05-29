import { useEffect, useState } from 'react';

const BACKEND_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5001';
const REFRESH_MS = 2500;

function App() {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('checking');
  const [lastUpdated, setLastUpdated] = useState('');
  const [error, setError] = useState('');
  const [feedVersion, setFeedVersion] = useState(0);
  const [modules, setModules] = useState(null);

  useEffect(() => {
    let isMounted = true;

    const fetchDashboardData = async () => {
      try {
        const [logsResponse, modulesResponse] = await Promise.all([
          fetch(`${BACKEND_URL}/api/logs`),
          fetch(`${BACKEND_URL}/api/modules`).catch(() => null),
        ]);

        if (!logsResponse.ok) {
          throw new Error(`Backend returned ${logsResponse.status}`);
        }

        const data = await logsResponse.json();
        const moduleData = modulesResponse?.ok ? await modulesResponse.json() : null;

        if (isMounted) {
          setLogs(Array.isArray(data) ? data : []);
          setModules(moduleData);
          setStatus('online');
          setError('');
          setLastUpdated(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        }
      } catch (fetchError) {
        if (isMounted) {
          setStatus('offline');
          setError(fetchError.message || 'Unable to connect to backend');
        }
      }
    };

    fetchDashboardData();
    const intervalId = window.setInterval(fetchDashboardData, REFRESH_MS);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const highestThreat = logs.reduce((max, log) => Math.max(max, Number(log.threat) || 0), 0);
  const activeZones = new Set(logs.map((log) => log.zone).filter(Boolean)).size;
  const statusLabel = status === 'online' ? 'Backend Online' : status === 'offline' ? 'Backend Offline' : 'Checking Backend';
  const emotionStatus = modules?.emotion?.status === 'enabled' ? 'Enabled' : 'Waiting';
  const knownFaceCount = modules?.knownFaces?.count ?? 0;

  return (
    <main className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-shield" aria-hidden="true">PC</span>
          <div>
            <p>Project Chanakya</p>
            <h1>AI Surveillance Command Dashboard</h1>
          </div>
        </div>
        <div className={`backend-status ${status}`}>
          <span />
          {statusLabel}
        </div>
      </header>

      <section className="hero-panel">
        <div>
          <p className="eyebrow">Flask backend connected at {BACKEND_URL}</p>
          <h2>Real-time smart surveillance interface</h2>
          <p>
            Live camera feeds, emotion signals, threat logs, incident zones, and secure report
            downloads are pulled directly from your Python backend.
          </p>
        </div>
        <div className="hero-actions">
          <button type="button" onClick={() => setFeedVersion((version) => version + 1)}>
            Refresh Feeds
          </button>
          <a href={`${BACKEND_URL}/download_secure_report`}>Download Report</a>
        </div>
      </section>

      {status === 'offline' && (
        <section className="alert-box">
          <strong>Backend connection failed.</strong>
          <span>{error}</span>
          <small>Start Flask with: venv/bin/python web/app.py</small>
        </section>
      )}

      <section className="metrics-grid" aria-label="System metrics">
        <MetricCard label="Backend" value={status === 'online' ? 'Connected' : 'Offline'} />
        <MetricCard label="Recent Logs" value={String(logs.length)} />
        <MetricCard label="Highest Threat" value={`${highestThreat}%`} danger={highestThreat >= 80} />
        <MetricCard label="Active Zones" value={String(activeZones)} />
        <MetricCard label="Emotion AI" value={emotionStatus} />
      </section>

      <section className="dashboard-grid">
        <div className="panel feeds-panel">
          <PanelHeader title="Live Camera Feeds" subtitle="MJPEG streams from Flask" />
          <div className="feed-grid">
            <CameraFeed title="ALPHA - Master Camera" src={`${BACKEND_URL}/video_feed_1?v=${feedVersion}`} />
            <CameraFeed title="BRAVO - Perimeter Camera" src={`${BACKEND_URL}/video_feed_2?v=${feedVersion}`} />
          </div>
        </div>

        <div className="panel logs-panel">
          <PanelHeader title="Threat Logs" subtitle={lastUpdated ? `Last sync ${lastUpdated}` : 'Waiting for backend'} />
          <ThreatLogs logs={logs} />
        </div>
      </section>

      <section className="panel project-info">
        <PanelHeader title="Project Abstract" subtitle="Submission-ready summary" />
        <div className="abstract-grid">
          <InfoBlock title="Objective" text="Detect suspicious activity through AI-enabled camera monitoring and show alerts on a web dashboard." />
          <InfoBlock title="Features" text={`Live feeds, YOLO threat logs, emotion signals, zone status, ${knownFaceCount} known face profiles, and reports.`} />
          <InfoBlock title="Technologies" text="React, Vite, Flask, OpenCV, YOLOv8, SQLite, facial landmarks, Python, and CSS." />
          <InfoBlock title="Outcome" text="A working full-stack surveillance prototype with a frontend connected to the backend APIs." />
        </div>
      </section>
    </main>
  );
}

function MetricCard({ label, value, danger = false }) {
  return (
    <article className={danger ? 'metric-card danger' : 'metric-card'}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function PanelHeader({ title, subtitle }) {
  return (
    <div className="panel-header">
      <div>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function CameraFeed({ title, src }) {
  const [hasError, setHasError] = useState(false);

  return (
    <article className="camera-card">
      <div className="camera-title">
        <span>{title}</span>
        <i>LIVE</i>
      </div>
      <div className="camera-frame">
        {!hasError ? (
          <img src={src} alt={`${title} live surveillance feed`} onError={() => setHasError(true)} />
        ) : (
          <div className="feed-fallback">
            <strong>Feed unavailable</strong>
            <span>Check camera permission or backend stream.</span>
          </div>
        )}
      </div>
    </article>
  );
}

function ThreatLogs({ logs }) {
  if (logs.length === 0) {
    return (
      <div className="empty-state">
        <strong>No incidents yet</strong>
        <span>Logs will appear here when the backend records detections.</span>
      </div>
    );
  }

  return (
    <div className="log-table" role="table" aria-label="Recent threat logs">
      <div className="log-row head" role="row">
        <span>Time</span>
        <span>Object</span>
        <span>Zone</span>
        <span>Threat</span>
      </div>
      {logs.map((log, index) => {
        const threat = Number(log.threat) || 0;

        return (
          <div className="log-row" role="row" key={`${log.timestamp}-${log.object}-${index}`}>
            <span>{log.timestamp || 'Unknown'}</span>
            <span>{log.object || 'Unknown object'}</span>
            <span>{log.zone || 'N/A'}</span>
            <strong className={threat >= 80 ? 'high-threat' : ''}>{threat}%</strong>
          </div>
        );
      })}
    </div>
  );
}

function InfoBlock({ title, text }) {
  return (
    <article className="info-block">
      <h4>{title}</h4>
      <p>{text}</p>
    </article>
  );
}

export default App;
