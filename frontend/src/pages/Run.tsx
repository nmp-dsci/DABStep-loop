import { Link, useParams } from 'react-router-dom';
import { type RunMeta, type TaskResult, fmtS, useGet, when } from '../lib/api';

export function Run() {
  const { runId = '' } = useParams();
  const { data, error } = useGet<{ meta: RunMeta; results: TaskResult[] }>(`/api/runs/${runId}`);
  if (error) return <div className="empty">{error}</div>;
  if (!data) return <p className="muted">loading…</p>;
  const { meta, results } = data;
  const s = meta.summary;
  return (
    <>
      <p className="label">
        <Link to="/runs">runs</Link> / {meta.agent}
      </p>
      <h1>
        {meta.agent} on {meta.split}: <em>{s?.n_scored ? `${s.passed} of ${s.n_scored}` : `${meta.n_tasks} answered`}</em>
      </h1>
      <p className="lead">
        {meta.model} · {meta.workers} workers · {meta.passes} pass{meta.passes > 1 ? 'es' : ''} · started {when(meta.started_at)} ·{' '}
        {fmtS(s?.duration_ms)} total · fingerprint <code>{meta.fingerprint}</code>
        {meta.note ? ` · ${meta.note}` : ''}
      </p>
      <div className="chips">
        <span className="chip">easy {s?.easy_passed}/{s?.easy_n}</span>
        <span className="chip">hard {s?.hard_passed}/{s?.hard_n}</span>
        <span className={`chip ${s?.errored_ids.length ? 'warn' : ''}`}>errors {s?.errored_ids.length ?? 0}</span>
        <span className="chip">
          tokens {results.reduce((n, r) => n + r.input_tokens, 0).toLocaleString()} in / {results.reduce((n, r) => n + r.output_tokens, 0).toLocaleString()} out
        </span>
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>task</th>
              <th>level</th>
              <th>verdict</th>
              <th>agent answer</th>
              <th>gold</th>
              <th className="num">turns</th>
              <th className="num">time</th>
              <th>ended</th>
              <th>trace</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.task_id}>
                <td className="sub num">{r.task_id}</td>
                <td>{r.level}</td>
                <td>
                  {r.correct === true ? <span className="status ok">pass</span> : r.correct === false ? <span className="status err">fail</span> : <span className="status no">unscored</span>}
                </td>
                <td className="wrap mono">{r.agent_answer.length > 90 ? r.agent_answer.slice(0, 90) + '…' : r.agent_answer}</td>
                <td className="wrap mono">{r.gold.length > 90 ? r.gold.slice(0, 90) + '…' : r.gold || '—'}</td>
                <td className="num">{r.n_turns}</td>
                <td className="num">{fmtS(r.duration_ms)}</td>
                <td className="small">
                  {r.terminal_reason ?? '—'}
                  {r.error && <span className="path v-warn">{r.error.slice(0, 80)}</span>}
                </td>
                <td>
                  <Link to={`/runs/${runId}/traces/${r.task_id}`}>open</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details>
        <summary>the agent files this run used</summary>
        <p className="small muted">
          Copied into <code>runs/{runId}/agent/</code> at run time; see <Link to={`/agents/${meta.agent}`}>{meta.agent}</Link> for the version.
        </p>
      </details>
    </>
  );
}
