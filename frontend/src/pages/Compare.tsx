import { useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { type Registry, type RunMeta, type TaskResult, shortRun, useGet } from '../lib/api';

type Verdict = { promote: boolean; champion_passed: number; challenger_passed: number; n: number; fixed: string[]; broken: string[]; reason: string };
type ComparePayload = { verdict: Verdict; rows: { task_id: string; level: string; a: TaskResult | null; b: TaskResult | null }[] };

export function Compare() {
  const [sp, setSp] = useSearchParams();
  const { data: runs } = useGet<RunMeta[]>('/api/runs');
  const { data: reg } = useGet<Registry>('/api/registry');
  const real = (runs ?? []).filter((r) => !r.dry_run && r.summary?.n_scored);
  const a = sp.get('a') ?? '';
  const b = sp.get('b') ?? '';
  useEffect(() => {
    if (!a && !b && reg?.champion && real.length) {
      const champ = reg.champion.run_id;
      const other = reg.challenger?.run_id ?? real.filter((r) => r.run_id !== champ).slice(-1)[0]?.run_id ?? champ;
      setSp({ a: champ, b: other }, { replace: true });
    }
  }, [a, b, reg, real, setSp]);
  const { data } = useGet<ComparePayload>(a && b ? `/api/compare?a=${a}&b=${b}` : null);
  const v = data?.verdict;
  return (
    <>
      <p className="label">Promotion gate</p>
      <h1>
        A challenger is promoted only if it flips <em>nothing</em> that passed
      </h1>
      <p className="lead">
        Two conditions, both required: more passes than the champion, and no task that the champion passed now fails. A
        version that fixes three and breaks one has learnt something wrong.
      </p>
      <div className="row">
        <label style={{ flex: '1 1 320px' }}>
          <span className="label">champion run</span>
          <select value={a} onChange={(e) => setSp({ a: e.target.value, b })}>
            <option value="">—</option>
            {real.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {shortRun(r.run_id)} · {r.summary?.passed}/{r.summary?.n_scored}
              </option>
            ))}
          </select>
        </label>
        <label style={{ flex: '1 1 320px' }}>
          <span className="label">challenger run</span>
          <select value={b} onChange={(e) => setSp({ a, b: e.target.value })}>
            <option value="">—</option>
            {real.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {shortRun(r.run_id)} · {r.summary?.passed}/{r.summary?.n_scored}
              </option>
            ))}
          </select>
        </label>
      </div>
      {v && (
        <div className="kpis">
          <div className="kpi">
            <div className="label">verdict</div>
            <div className={`n ${v.promote ? 'ok' : 'warn'}`}>{v.promote ? 'promote' : 'hold'}</div>
            <div className="b">{v.reason}</div>
          </div>
          <div className="kpi">
            <div className="label">passes</div>
            <div className="n">
              {v.champion_passed} → {v.challenger_passed}
            </div>
            <div className="b">of {v.n} scored tasks</div>
          </div>
          <div className="kpi">
            <div className="label">fixed</div>
            <div className="n ok">{v.fixed.length}</div>
            <div className="b mono">{v.fixed.join(', ') || '—'}</div>
          </div>
          <div className="kpi">
            <div className="label">broken</div>
            <div className={`n ${v.broken.length ? 'warn' : ''}`}>{v.broken.length}</div>
            <div className="b mono">{v.broken.join(', ') || '—'}</div>
          </div>
        </div>
      )}
      {data && (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>task</th>
                <th>level</th>
                <th>champion</th>
                <th>challenger</th>
                <th>change</th>
                <th>champion answer</th>
                <th>challenger answer</th>
                <th>gold</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => {
                const ca = r.a?.correct;
                const cb = r.b?.correct;
                const change = ca === cb ? '' : cb ? 'fixed' : 'broken';
                return (
                  <tr key={r.task_id} className={change === 'fixed' ? 'pro' : ''}>
                    <td className="sub num">
                      <Link to={`/runs/${b}/traces/${r.task_id}`}>{r.task_id}</Link>
                    </td>
                    <td>{r.level}</td>
                    <td>{ca == null ? '—' : ca ? <span className="status ok">pass</span> : <span className="status err">fail</span>}</td>
                    <td>{cb == null ? '—' : cb ? <span className="status ok">pass</span> : <span className="status err">fail</span>}</td>
                    <td className={change === 'fixed' ? 'v-ok' : change === 'broken' ? 'v-warn' : 'v-no'}>{change || 'same'}</td>
                    <td className="wrap mono small">{(r.a?.agent_answer ?? '').slice(0, 60)}</td>
                    <td className="wrap mono small">{(r.b?.agent_answer ?? '').slice(0, 60)}</td>
                    <td className="wrap mono small">{(r.a?.gold ?? r.b?.gold ?? '').slice(0, 60)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
