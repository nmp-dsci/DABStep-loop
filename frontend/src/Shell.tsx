import { NavLink, Outlet } from 'react-router-dom';
import { type Health, useGet } from './lib/api';

const NAV: [string, string][] = [
  ['/', 'Result'],
  ['/data', 'Data'],
  ['/tasks', 'Tasks'],
  ['/architecture', 'Architecture'],
  ['/agents', 'Agents'],
  ['/runs', 'Runs'],
  ['/compare', 'Gate'],
  ['/loop', 'Loop'],
  ['/evolution', 'Evolution'],
  ['/ask', 'Ask'],
];

export function Shell() {
  const { data: health } = useGet<Health>('/healthz');
  return (
    <>
      <header className="top">
        <div className="in">
          <NavLink to="/" className="brand">
            <img src="/favicon.svg" alt="" width="22" height="22" />
            <span>
              DABstep<b>-loop</b>
            </span>
          </NavLink>
          <nav aria-label="Pages">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')}>
                {label}
              </NavLink>
            ))}
          </nav>
          <span className={`mode ${health?.mode === 'live' ? 'live' : ''}`} title="demo replays recorded runs and never calls a model">
            {health ? (health.mode === 'demo' ? 'demo · replay only' : 'live · dev') : '…'}
          </span>
        </div>
      </header>
      <main>
        <Outlet context={health} />
      </main>
      <footer>
        Every number on these pages is read from a committed file in the repo: <code>runs/</code>, <code>agents/</code>,{' '}
        <code>loop/ledger.jsonl</code>, <code>data/</code>. Build <code>{health?.code_sha ?? '…'}</code>.{' '}
        <a href="https://github.com/nmp-dsci/DABStep-loop">Source</a>.
      </footer>
    </>
  );
}
