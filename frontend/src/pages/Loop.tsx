import { Link } from 'react-router-dom';
import { type LedgerEntry, fmtK, fmtS, shortRun, useGet } from '../lib/api';

export function Loop() {
  const { data: ledger } = useGet<LedgerEntry[]>('/api/ledger');
  const entries = ledger ?? [];
  return (
    <>
      <p className="label">The ledger</p>
      <h1>
        Every diagnosis is kept, so the loop does not <em>repeat</em> a failed fix
      </h1>
      <p className="lead">
        This is <code>loop/ledger.jsonl</code>, rendered. The optimiser writes the diagnoses; the harness writes the outcome after the
        gate. The next cycle's optimiser is shown this page's contents before it proposes anything.
      </p>
      {entries.length === 0 && <div className="empty">No cycle has run. <code>make loop</code> starts one.</div>}
      {entries.map((e) => (
        <section key={`${e.kind}-${e.cycle}`} className="band" style={{ marginTop: 'var(--s6)' }}>
          <h2 style={{ marginTop: 0 }}>
            {e.kind === 'cycle' ? `cycle ${e.cycle}` : `${e.kind} ${e.cycle}`} — {e.kind === 'cycle' ? `${e.champion} → ${e.challenger ?? '—'}` : e.champion}:{' '}
            {e.outcome?.verdict ?? 'pending'}
            {e.outcome?.passes ? ` (${e.outcome.passes})` : ''}
          </h2>
          <div className="chips">
            {e.optimiser_model && <span className="chip">optimiser {e.optimiser_model}</span>}
            {e.optimiser && <span className="chip">{e.optimiser.turns} turns · {fmtS(e.optimiser.duration_ms)}</span>}
            {e.tokens && (
              <span className="chip">
                tokens opt {fmtK(e.tokens.optimiser_in)}/{fmtK(e.tokens.optimiser_out)} · eval {fmtK(e.tokens.eval_in)}/{fmtK(e.tokens.eval_out)}
              </span>
            )}
            {e.outcome?.fixed?.length ? <span className="chip ok">fixed {e.outcome.fixed.join(', ')}</span> : null}
            {e.outcome?.broken?.length ? <span className="chip warn">broken {e.outcome.broken.join(', ')}</span> : null}
            {e.outcome?.still_failed?.length ? <span className="chip no">still failed {e.outcome.still_failed.join(', ')}</span> : null}
            {e.outcome?.challenger_run && (
              <Link className="chip" to={`/compare?a=${e.champion_run ?? ''}&b=${e.outcome.challenger_run}`}>
                gate view · {shortRun(e.outcome.challenger_run)}
              </Link>
            )}
          </div>
          {e.kind === 'cycle' && (
            <dl className="diff-sum">
              <dt>prompt</dt>
              <dd>{e.prompt_diff_summary || '—'}</dd>
              <dt>helper</dt>
              <dd>{e.helper_diff_summary || '—'}</dd>
              {e.outcome?.reason && (
                <>
                  <dt>reason</dt>
                  <dd>{e.outcome.reason}</dd>
                </>
              )}
              {e.optimiser?.error && (
                <>
                  <dt>harness</dt>
                  <dd className="v-warn">{e.optimiser.error}</dd>
                </>
              )}
            </dl>
          )}
          {e.kind !== 'cycle' && (
            <>
              <p>{e.summary}</p>
              {e.notes?.length ? (
                <ul>
                  {e.notes.map((n, i) => (
                    <li key={i} className="small">{String(n)}</li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
          {e.diagnoses?.length ? (
            <div className="tw">
              <table>
                <thead>
                  <tr>
                    <th>task</th>
                    <th>symptom</th>
                    <th>root cause</th>
                    <th>surface</th>
                    <th>change</th>
                    <th>verified</th>
                    <th>outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {e.diagnoses.map((d) => {
                    const o: NonNullable<LedgerEntry["outcome"]> = e.outcome ?? { verdict: "pending" };
                    const res = o.fixed?.includes(d.task_id) ? 'fixed' : o.broken?.includes(d.task_id) ? 'broken' : o.still_failed?.includes(d.task_id) ? 'still failed' : o.verdict === 'pending' ? 'pending' : 'unchanged';
                    return (
                      <tr key={d.task_id + d.surface}>
                        <td className="sub num">{d.task_id}</td>
                        <td className="wrap">{d.symptom}</td>
                        <td className="wrap">{d.root_cause}</td>
                        <td className="mono">{d.surface}</td>
                        <td className="wrap">{d.change}</td>
                        <td>{d.verified_in_session ? <span className="v-ok">yes</span> : <span className="v-warn">no</span>}</td>
                        <td className={res === 'fixed' ? 'v-ok' : res === 'broken' || res === 'still failed' ? 'v-warn' : 'v-no'}>{res}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
          {e.risks?.length ? (
            <details>
              <summary>risks the optimiser named</summary>
              <ul>
                {e.risks.map((r, i) => (
                  <li key={i} className="small">{r}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
      ))}
    </>
  );
}
