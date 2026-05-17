import { useEffect, useState } from 'react';

const NAV_ITEMS = [
  { id: 'home', label: 'HOME' },
  { id: 'operations', label: 'OPERATIONS' },
  { id: 'hardware', label: 'INTEL VAULT' },
  { id: 'contact', label: 'GET IN TOUCH' },
];

const STATS = [
  '60 FPS // M4 NEURAL ENGINE',
  'AES-256 // ENCRYPTION',
  '5+ CLASSES // YOLOV8',
  '<2SEC // TELEGRAM ALERT',
];

const CAMERAS = [
  { id: 'CAM_01', label: 'ACTIVE' },
  { id: 'CAM_02', label: 'OFFLINE' },
  { id: 'CAM_03', label: 'ACTIVE' },
  { id: 'CAM_04', label: 'MOTION' },
];

const SPECS = [
  ['Model', 'AI-X90 Surveillance Core'],
  ['OS', 'Mil-Spec iOS'],
  ['Connection', 'Encrypted SatLink'],
  ['Processor', 'Apple M4 Neural Engine'],
  ['Detection', 'YOLOv8-M (Real-Time)'],
];

function ShieldIcon({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2.8 20 6v5.8c0 4.6-3.2 8.4-8 9.8-4.8-1.4-8-5.2-8-9.8V6l8-3.2Z" />
      <path d="M12 6.3v11.2" />
      <path d="M8.2 9.5h7.6" />
    </svg>
  );
}

function SimpleIcon({ type, className = '' }) {
  const paths = {
    drone: (
      <>
        <path d="M8 12h8M12 8v8M4.5 7.5l4 4-4 4M19.5 7.5l-4 4 4 4" />
        <circle cx="4.5" cy="7.5" r="2.2" />
        <circle cx="19.5" cy="7.5" r="2.2" />
        <circle cx="4.5" cy="15.5" r="2.2" />
        <circle cx="19.5" cy="15.5" r="2.2" />
      </>
    ),
    monitor: (
      <>
        <rect x="4" y="5" width="16" height="11" rx="1.5" />
        <path d="M9 20h6M12 16v4" />
      </>
    ),
    map: (
      <>
        <path d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2V6Z" />
        <path d="M9 4v14M15 6v14" />
      </>
    ),
    alert: (
      <>
        <path d="M12 3 21 20H3L12 3Z" />
        <path d="M12 9v5M12 17h.01" />
      </>
    ),
    gear: (
      <>
        <circle cx="12" cy="12" r="3.2" />
        <path d="M12 2.8v3M12 18.2v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2.8 12h3M18.2 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
      </>
    ),
    chip: (
      <>
        <rect x="7" y="7" width="10" height="10" rx="1.4" />
        <path d="M9 3v4M12 3v4M15 3v4M9 17v4M12 17v4M15 17v4M3 9h4M3 12h4M3 15h4M17 9h4M17 12h4M17 15h4" />
      </>
    ),
    back: <path d="M15 5 8 12l7 7" />,
  };

  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      {paths[type]}
    </svg>
  );
}

function FixedNav({ activePage, setPage }) {
  return (
    <header className="site-nav">
      <button className="brand-mark" type="button" onClick={() => setPage('home')}>
        <ShieldIcon className="brand-icon" />
        <span>PROJECT CHANAKYA</span>
      </button>
      <nav aria-label="Primary navigation">
        {NAV_ITEMS.map((item) => (
          <button
            className={activePage === item.id ? 'nav-link active' : 'nav-link'}
            key={item.id}
            type="button"
            onClick={() => setPage(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
    </header>
  );
}

function App() {
  const [page, setPage] = useState('home');
  const [time, setTime] = useState('23:45');

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }));
    };

    updateClock();
    const timer = window.setInterval(updateClock, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const visiblePage = page === 'contact' ? 'home' : page;

  return (
    <main className={`app-shell page-${visiblePage}`}>
      <FixedNav activePage={page} setPage={setPage} />
      {visiblePage === 'home' && <HeroLanding setPage={setPage} />}
      {visiblePage === 'operations' && <OperationsCommandCenter time={time} setPage={setPage} />}
      {visiblePage === 'hardware' && <HardwareStatus setPage={setPage} />}
    </main>
  );
}

function HeroLanding({ setPage }) {
  return (
    <section className="hero-screen" aria-label="Project Chanakya landing page">
      <div className="hero-stage" />
      <div className="hero-copy">
        <p className="eyebrow">AUTONOMOUS BORDER INTELLIGENCE</p>
        <h1>
          AUTONOMOUS SURVEILLANCE.
          <span>AI ACCELERATED.</span>
        </h1>
        <p>
          Project Chanakya fuses aerial detection, neural threat assessment, encrypted incident
          reporting, and live command telemetry into one hardened surveillance interface.
        </p>
        <div className="hero-actions">
          <button type="button" className="cta primary" onClick={() => setPage('operations')}>
            LAUNCH COMMAND HUB
          </button>
          <button type="button" className="cta secondary" onClick={() => setPage('hardware')}>
            INTEL VAULT
          </button>
        </div>
      </div>
      <div className="scroll-cue">
        <span>SCROLL</span>
        <i />
      </div>
      <div className="stats-strip">
        {STATS.map((stat) => (
          <span key={stat}>{stat}</span>
        ))}
      </div>
    </section>
  );
}

function OperationsCommandCenter({ time, setPage }) {
  return (
    <section className="ops-screen" aria-label="Operations Command Center">
      <div className="ops-topbar">
        <strong>{time}</strong>
        <div>
          <h2>DEFENSE COMMAND CENTER</h2>
          <p>Border Security Operations - Night Shift</p>
        </div>
        <span>SIG 4G&nbsp;&nbsp;BAT 85</span>
      </div>
      <div className="monitor-array">
        <MonitorTerrain />
        <MonitorHeatmap />
        <MonitorGrid />
      </div>
      <div className="command-desk">
        <div className="keyboard-line" />
        <div className="force-watermark">
          <ShieldIcon />
          <span>INDIAN BORDER DEFENSE FORCE</span>
        </div>
      </div>
      <button className="deploy-button" type="button">
        DEPLOY RESPONSE
      </button>
      <OpsTabs setPage={setPage} />
    </section>
  );
}

function MonitorTerrain() {
  return <article className="monitor-card monitor-terrain" />;
}

function MonitorHeatmap() {
  return <article className="monitor-card monitor-heatmap" />;
}

function MonitorGrid() {
  return (
    <article className="monitor-card monitor-grid">
      {CAMERAS.map((camera) => (
        <div className="camera-tile" key={camera.id}>
          <span>{camera.id} {camera.label}</span>
        </div>
      ))}
    </article>
  );
}

function OpsTabs({ setPage }) {
  const tabs = [
    ['DRONE CONTROL', 'drone', 'operations'],
    ['LIVE FEEDS', 'monitor', 'operations'],
    ['OPERATIONS', 'map', 'operations'],
    ['ALERTS', 'alert', 'operations'],
    ['SETTINGS', 'gear', 'hardware'],
  ];

  return (
    <nav className="ops-tabs" aria-label="Operations tabs">
      {tabs.map(([label, icon, target], index) => (
        <button className={index === 2 ? 'active' : ''} type="button" key={label} onClick={() => setPage(target)}>
          <SimpleIcon type={icon} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

function HardwareStatus({ setPage }) {
  return (
    <section className="hardware-screen" aria-label="Hardware Status">
      <div className="hardware-device">
        <header className="hardware-header">
          <button type="button" onClick={() => setPage('operations')}>
            <SimpleIcon type="back" />
            Back
          </button>
          <h2>AI Surveillance Hardware Detail</h2>
        </header>
        <div className="pcb-hero" />
        <section className="hardware-panel">
          <h3>HARDWARE STATUS</h3>
          <p className="active-link">ACTIVE - SECURE LINK ESTABLISHED</p>
          <h4>SPECIFICATIONS</h4>
          <dl>
            {SPECS.map(([label, value]) => (
              <div key={label}>
                <dt>{label}:</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        <HardwareTabs setPage={setPage} />
      </div>
    </section>
  );
}

function HardwareTabs({ setPage }) {
  const tabs = [
    ['MAP', 'map', 'home'],
    ['DRONES', 'drone', 'operations'],
    ['HARDWARE', 'chip', 'hardware'],
    ['SETTINGS', 'gear', 'hardware'],
  ];

  return (
    <nav className="hardware-tabs" aria-label="Hardware tabs">
      {tabs.map(([label, icon, target]) => (
        <button className={label === 'HARDWARE' ? 'active' : ''} type="button" key={label} onClick={() => setPage(target)}>
          <SimpleIcon type={icon} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

export default App;
