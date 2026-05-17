import { useState, useEffect } from 'react';
import { Shield, Download, Eye, Radar, AlertTriangle, LayoutDashboard } from 'lucide-react';

const BACKEND_URL = 'http://127.0.0.1:5001';

export default function App() {
  const [logs, setLogs] = useState([]);
  const [networkStatus, setNetworkStatus] = useState('ACTIVE');

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/logs`);
        if (response.ok) {
          const data = await response.json();
          setLogs(data);
          setNetworkStatus('ACTIVE');
        }
      } catch {
        setNetworkStatus('OFFLINE');
      }
    };

    fetchLogs();
    const interval = setInterval(fetchLogs, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-shell">
      <div className="hud-panel">
        <div className="hud-header">
          <div className="brand">
            <Shield className="icon text-neon-green" />
            <div className="brand-title">
              PROJECT<br />CHANAKYA
            </div>
          </div>
          <div className={`network-badge ${networkStatus === 'ACTIVE' ? 'active' : 'offline'}`}>
            [{networkStatus === 'ACTIVE' ? 'NETWORK ACTIVE' : 'OFFLINE'}]
          </div>
        </div>

        <div className="hud-content">
          <div className="feed-section">
            <div className="feed-title">
              <span>FEED: ALPHA (MASTER)</span>
              <span className="text-neon-red">REC 00:42:19</span>
            </div>
            <div className="feed-frame alpha cyber-corners">
              <img
                src={`${BACKEND_URL}/video_feed_1`}
                alt="Alpha"
                className="feed-image alpha-image"
                onError={(event) => { event.target.style.display = 'none'; }}
              />
            </div>
          </div>

          <div className="feed-section">
            <div className="feed-title">
              <span>FEED: BRAVO (PERIMETER)</span>
              <span className="text-neon-green">LIVE TRANS-84</span>
            </div>
            <div className="feed-frame bravo cyber-corners">
              <img
                src={`${BACKEND_URL}/video_feed_2`}
                alt="Bravo"
                className="feed-image bravo-image"
                onError={(event) => { event.target.style.display = 'none'; }}
              />
            </div>
          </div>

          <div className="log-panel cyber-corners">
            <div className="log-title">THREAT_LOG.EXE</div>
            <div className="log-list">
              {logs.length === 0 ? (
                <p className="empty-log">WAITING FOR DATA...</p>
              ) : (
                logs.slice(0, 4).map((log, index) => (
                  <div key={`${log.timestamp}-${index}`} className="log-row">
                    <span className="text-cyber-text">[{new Date().toLocaleTimeString()}]</span>
                    <span className={parseInt(log.threat, 10) > 70 ? 'text-neon-red bold' : 'text-cyber-text'}>
                      {log.object.toUpperCase()}
                    </span>
                    <span className={parseInt(log.threat, 10) > 70 ? 'text-neon-red' : 'text-neon-green'}>{log.threat}%</span>
                  </div>
                ))
              )}
            </div>
          </div>

          <a
            href={`${BACKEND_URL}/download_secure_report`}
            className="download-button"
          >
            <Download className="small-icon" />
            <span>DOWNLOAD SECURE BRIEFING</span>
          </a>
        </div>

        <div className="hud-nav">
          <div className="nav-item active">
            <Eye className="icon nav-icon" />
            <span>Observe</span>
          </div>
          <Radar className="icon nav-icon" />
          <AlertTriangle className="icon nav-icon" />
          <LayoutDashboard className="icon nav-icon" />
        </div>
      </div>
    </div>
  );
}
