import { Link } from 'react-router-dom';
import { type RunMeta, fmtS, shortRun, useGet, when } from '../lib/api';

type Snapshot = { experiment: string | null; tracking_uri?: string; runs: { name: string; tags: Record<string, string>; metrics: Record<string, number>; params: Record<string, string> }[] };

export function Runs() {
  const { data: runs } = useGet<RunMeta[]>('/api/runs');
  const { data: snap } = useGet<Snapshot>('/api/experiments');
  const real = (runs ?? []).filter((r) => !r.dry_run).slice().reverse();
  return (
    <>
      <p className="label">Evaluation runs</p>
      <h1>
        A run is a <em>folder</em>: results, traces, the exact agent files
      </h1>
      <p className="lead">
        Each row is <code>runs/&lt;id&gt;/</code> in the repo. MLflow indexes the same folders; the snapshot below is what the tracker
        holds, exported for this page so the public demo needs no server.
      </p>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>run</th>
              <th>agent</th>
              <th>model</th>
              <th>split</th>
              <th className="num">pass</th>
              <th className="num">easy</th>
              <th className="num">hard</th>
              <th className="num">errors</th>
              <th className="num">time</th>
              <th>note</th>
            </tr>
          </thead>
          <tbody>
            {real.map((r) => (
              <tr key={r.run_id}>
                <td className="sub">
                  <Link to={`/runs/${r.run_id}`}>{shortRun(r.run_id)}</Link>
                  <span className="path">{when(r.started_at)}</span>
                </td>
                <td className="mono">{r.agent} · {r.fingerprint}</td>
                <td className="mono">{r.model.replace('claude-', '')}</td>
                <td>
                  {r.split}
                  {r.kind === 'probe' && <span className="path">unscored · {r.sample?.n ?? r.n_tasks} of the 450 · seed {r.sample?.seed}</span>}
                </td>
                <td className="num">{r.kind === 'probe' ? 'n/a' : r.summary?.n_scored ? `${r.summary.passed}/${r.summary.n_scored}` : '—'}</td>
                <td className="num">{r.summary ? `${r.summary.easy_passed}/${r.summary.easy_n}` : '—'}</td>
                <td className="num">{r.summary ? `${r.summary.hard_passed}/${r.summary.hard_n}` : '—'}</td>
                <td className="num">{r.summary?.errored_ids.length ?? '—'}</td>
                <td className="num">{fmtS(r.summary?.duration_ms)}</td>
                <td className="wrap small muted">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {real.length === 0 && <div className="empty">No runs committed yet.</div>}

      <h2>MLflow snapshot — {snap?.runs.length ?? 0} tracked runs in experiment {snap?.experiment ?? '—'}</h2>
      {snap && snap.runs.length > 0 ? (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>name</th>
                <th>kind</th>
                <th>agent</th>
                <th className="num">pass_rate</th>
                <th className="num">cost est.</th>
                <th className="num">turns</th>
                <th className="num">input tok</th>
                <th className="num">output tok</th>
              </tr>
            </thead>
            <tbody>
              {snap.runs.map((r) => (
                <tr key={r.name}>
                  <td className="sub mono">{shortRun(r.name)}</td>
                  <td>{r.tags.kind ?? '—'}</td>
                  <td className="mono">{r.tags.agent ?? r.tags.challenger ?? '—'}</td>
                  <td className="num">{r.metrics.pass_rate != null ? `${Math.round(r.metrics.pass_rate * 100)}%` : '—'}</td>
                  <td className="num">{r.metrics.cost_usd != null ? `$${r.metrics.cost_usd.toFixed(2)}` : '—'}</td>
                  <td className="num">{r.metrics.turns_total ?? '—'}</td>
                  <td className="num">{r.metrics.input_tokens?.toLocaleString() ?? '—'}</td>
                  <td className="num">{r.metrics.output_tokens?.toLocaleString() ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">No snapshot committed. <code>make snapshot</code> exports the experiment.</div>
      )}
      <p className="small muted">
        "cost est." is the SDK's per-token estimate; dev runs bill the subscription, so the amount paid was $0.
      </p>
    </>
  );
}
