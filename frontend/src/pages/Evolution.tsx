import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { type AgentInfo, type Diagnosis, type LedgerEntry, type Registry, type RunMeta, shortRun, useGet } from '../lib/api';

type Side = { name: string; fingerprint: string; runs: RunMeta[] };
type DiffFile = { name: string; changed: boolean; added: number; removed: number; diff: string[]; before: string; after: string };
type Change = { file: string; anchor: string; what: string; why: string; task_ids: string[] };
type DiffPayload = {
  a: Side;
  b: Side;
  files: DiffFile[];
  change_log: { source: 'in-session' | 'post-hoc'; changes: Change[] } | null;
  closing_account: string | null;
  diagnosis: { diagnoses: Diagnosis[]; prompt_diff_summary: string; helper_diff_summary: string; expected_to_fix: string[]; risks: string[] } | null;
  cycles: LedgerEntry[];
};

type Hunk = { header: string; lines: string[] };

function hunks(diff: string[]): Hunk[] {
  const out: Hunk[] = [];
  for (const line of diff.slice(2)) {
    if (line.startsWith('@@')) out.push({ header: line, lines: [] });
    else out[out.length - 1]?.lines.push(line);
  }
  return out;
}

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9_]+/g, ' ').trim();

/** The change-log entries whose anchor text appears in this hunk's added or removed lines. */
function commentaryFor(h: Hunk, changes: Change[], file: string): Change[] {
  const body = norm(h.lines.filter((l) => l.startsWith('+') || l.startsWith('-')).join(' '));
  return changes.filter((c) => c.file === file && c.anchor && body.includes(norm(c.anchor).split(' ').slice(0, 5).join(' ')));
}

function best(runs: RunMeta[]): RunMeta | undefined {
  return runs.filter((r) => r.split === 'dev' && r.summary?.n_scored).slice(-1)[0];
}

export function Evolution() {
  const [sp, setSp] = useSearchParams();
  const { data: agents } = useGet<{ versions: AgentInfo[]; registry: Registry }>('/api/agents');
  const names = (agents?.versions ?? []).map((v) => v.name);
  const a = sp.get('a') ?? '';
  const b = sp.get('b') ?? '';
  const [file, setFile] = useState('system.md');
  useEffect(() => {
    if (!a && !b && names.length >= 2) setSp({ a: names[names.length - 2], b: names[names.length - 1] }, { replace: true });
  }, [a, b, names, setSp]);
  const { data } = useGet<DiffPayload>(a && b ? `/api/agents/diff?a=${a}&b=${b}` : null);
  const ra = data ? best(data.a.runs) : undefined;
  const rb = data ? best(data.b.runs) : undefined;
  const cur = data?.files.find((f) => f.name === file) ?? data?.files[0];
  const cycle = data?.cycles[0];

  return (
    <>
      <p className="label">How the agent changed</p>
      <h1>
        Pick a before and an after: the <em>diff</em>, and the reasoning that produced it
      </h1>
      <p className="lead">
        The optimiser may change two files. Every version's <code>diagnosis.json</code> says why each line changed and which
        failed task it was for; the ledger says what the gate then decided. Read the change and its reason side by side.
      </p>

      <div className="row">
        <label style={{ flex: '1 1 220px' }}>
          <span className="label">before</span>
          <select value={a} onChange={(e) => setSp({ a: e.target.value, b })}>
            {names.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <label style={{ flex: '1 1 220px' }}>
          <span className="label">after</span>
          <select value={b} onChange={(e) => setSp({ a, b: e.target.value })}>
            {names.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>

      {data && (
        <div className="kpis">
          <div className="kpi">
            <div className="label">{data.a.name} on dev-10</div>
            <div className="n">{ra?.summary ? `${ra.summary.passed}/${ra.summary.n_scored}` : '—'}</div>
            <div className="b">{ra ? <Link to={`/runs/${ra.run_id}`}>{shortRun(ra.run_id)}</Link> : 'no scored run'} · {data.a.fingerprint}</div>
          </div>
          <div className="kpi">
            <div className="label">{data.b.name} on dev-10</div>
            <div className={`n ${rb && ra && (rb.summary?.passed ?? 0) > (ra.summary?.passed ?? 0) ? 'ok' : ''}`}>{rb?.summary ? `${rb.summary.passed}/${rb.summary.n_scored}` : '—'}</div>
            <div className="b">{rb ? <Link to={`/runs/${rb.run_id}`}>{shortRun(rb.run_id)}</Link> : 'no scored run'} · {data.b.fingerprint}</div>
          </div>
          <div className="kpi">
            <div className="label">lines changed</div>
            <div className="n">
              <span className="v-ok">+{data.files.reduce((n, f) => n + f.added, 0)}</span> <span className="v-warn">−{data.files.reduce((n, f) => n + f.removed, 0)}</span>
            </div>
            <div className="b">{data.files.filter((f) => f.changed).map((f) => f.name).join(', ') || 'identical'}</div>
          </div>
          <div className="kpi">
            <div className="label">gate on {data.b.name}</div>
            <div className={`n ${cycle?.outcome?.verdict === 'promote' ? 'ok' : cycle?.outcome?.verdict === 'hold' ? 'warn' : ''}`}>{cycle?.outcome?.verdict ?? '—'}</div>
            <div className="b">{cycle ? `cycle ${cycle.cycle} · ${cycle.outcome?.passes ?? ''} · ${cycle.outcome?.reason ?? ''}` : 'not produced by the loop'}</div>
          </div>
        </div>
      )}

      {data?.diagnosis && (
        <>
          <h2>1 · Why {data.b.name} exists — the optimiser's diagnosis, one row per failed task</h2>
          <dl className="diff-sum">
            <dt>prompt</dt>
            <dd>{data.diagnosis.prompt_diff_summary}</dd>
            <dt>helper</dt>
            <dd>{data.diagnosis.helper_diff_summary}</dd>
          </dl>
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
                {data.diagnosis.diagnoses.map((d) => {
                  const o = cycle?.outcome;
                  const res = o?.fixed?.includes(d.task_id) ? 'fixed' : o?.broken?.includes(d.task_id) ? 'broken' : o?.still_failed?.includes(d.task_id) ? 'still failed' : '—';
                  return (
                    <tr key={d.task_id + d.surface}>
                      <td className="sub num">{d.task_id}</td>
                      <td className="wrap">{d.symptom}</td>
                      <td className="wrap">{d.root_cause}</td>
                      <td className="mono">{d.surface}</td>
                      <td className="wrap">{d.change}</td>
                      <td>{d.verified_in_session ? <span className="v-ok">yes</span> : <span className="v-warn">no</span>}</td>
                      <td className={res === 'fixed' ? 'v-ok' : res === '—' ? 'v-no' : 'v-warn'}>{res}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {data.diagnosis.risks?.length ? (
            <details>
              <summary>risks the optimiser named</summary>
              <ul>{data.diagnosis.risks.map((r, i) => <li key={i} className="small">{r}</li>)}</ul>
            </details>
          ) : null}
        </>
      )}
      {data && !data.diagnosis && <div className="empty">{data.b.name} has no diagnosis.json — it was not written by the optimiser (v0 is the hand-written baseline).</div>}

      {data && (
        <>
          <h2>2 · The diff — {data.a.name} → {data.b.name}</h2>
          <div className="chips" role="tablist">
            {data.files.map((f) => (
              <button key={f.name} role="tab" aria-selected={cur?.name === f.name} className={`chip ${cur?.name === f.name ? 'ok' : f.changed ? '' : 'no'}`} onClick={() => setFile(f.name)} style={{ cursor: 'pointer' }}>
                {f.name} {f.changed ? `+${f.added} −${f.removed}` : 'unchanged'}
              </button>
            ))}
          </div>
          {data.change_log && (
            <p className="small muted">
              Commentary above each hunk comes from the version's change log —{' '}
              {data.change_log.source === 'in-session' ? (
                <span className="v-ok">written by the optimiser in the same session as the edit.</span>
              ) : (
                <span className="v-warn">annotated post hoc by a read-only session from the optimiser's own diagnosis and transcript; edits whose reason the record does not state say so.</span>
              )}
            </p>
          )}
          {cur && (
            <div className="code diff">
              {cur.changed ? (
                <>
                  {hunks(cur.diff).map((h, hi) => {
                    const notes = data.change_log ? commentaryFor(h, data.change_log.changes, cur.name) : [];
                    return (
                      <div key={hi}>
                        {notes.map((c, ci) => (
                          <div key={ci} className="note">
                            <span className="label">why · tasks {c.task_ids.join(', ') || '—'}</span>
                            <b>{c.what}</b> {c.why}
                          </div>
                        ))}
                        <pre>
                          <span className="hunk">{h.header}{'\n'}</span>
                          {h.lines.map((line, i) => (
                            <span key={i} className={line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : 'ctx'}>
                              {line}
                              {'\n'}
                            </span>
                          ))}
                        </pre>
                      </div>
                    );
                  })}
                </>
              ) : (
                <pre className="muted">{cur.name} is identical in {data.a.name} and {data.b.name}{cur.name === 'agent.yaml' ? ' — frozen by design' : ''}.</pre>
              )}
            </div>
          )}

          {data.change_log && (
            <>
              <h2>3 · The change log — every edit, what it does, and the evidence for it</h2>
              <div className="tw">
                <table>
                  <thead>
                    <tr>
                      <th>file</th>
                      <th>anchor</th>
                      <th>what</th>
                      <th>why</th>
                      <th>tasks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.change_log.changes.map((c, i) => (
                      <tr key={i}>
                        <td className="mono">{c.file}</td>
                        <td className="mono small wrap">{c.anchor}</td>
                        <td className="wrap">{c.what}</td>
                        <td className={`wrap ${/not stated/i.test(c.why) ? 'v-warn' : ''}`}>{c.why}</td>
                        <td className="mono">{c.task_ids.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {data.closing_account && (
            <>
              <h2>4 · In the optimiser's own words — its closing account of the session</h2>
              <div className="code">
                <pre>{data.closing_account}</pre>
              </div>
              <p className="small muted">The last message of <code>agents/{data.b.name}/optimiser_transcript.json</code>, verbatim.</p>
            </>
          )}
        </>
      )}
    </>
  );
}
