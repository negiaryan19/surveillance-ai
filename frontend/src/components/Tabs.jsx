import { useRef } from 'react';
import { tabDomIds } from '../lib/tabIds.js';

/**
 * WAI-ARIA tablist with a roving tabindex: Tab enters/leaves the list, Left/Right/Home/End
 * move between tabs (and activate them, since switching views is cheap).
 *
 * @param {{tabs: {id: string, label: string, icon: Function}[], active: string, onChange: (id: string) => void}} props
 */
export default function Tabs({ tabs, active, onChange }) {
  const listRef = useRef(null);

  const focusTab = (id) => {
    listRef.current?.querySelector(`#${tabDomIds(id).tab}`)?.focus();
  };

  const onKeyDown = (event) => {
    const index = tabs.findIndex((tab) => tab.id === active);
    let next = null;
    if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
    else if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
    else if (event.key === 'Home') next = tabs[0];
    else if (event.key === 'End') next = tabs[tabs.length - 1];
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    focusTab(next.id);
  };

  return (
    <div className="tabs" role="tablist" aria-label="Dashboard sections" ref={listRef} onKeyDown={onKeyDown}>
      {tabs.map(({ id, label, icon: Icon }) => {
        const ids = tabDomIds(id);
        const selected = id === active;
        return (
          <button
            key={id}
            id={ids.tab}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={ids.panel}
            tabIndex={selected ? 0 : -1}
            className={selected ? 'tab active' : 'tab'}
            onClick={() => onChange(id)}
          >
            <Icon size={16} aria-hidden="true" />
            {label}
          </button>
        );
      })}
    </div>
  );
}
