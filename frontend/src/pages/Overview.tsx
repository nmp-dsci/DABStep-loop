import { Link } from 'react-router-dom';
import { type LedgerEntry, type Registry, type RunMeta, fmtK, shortRun, useGet } from '../lib/api';

export function Overview() {
  const { data: reg } = useGet<Registry>('/api/registry');
  const { data: runs } = useGet<RunMeta[]>('/api/runs');
  const { data: ledger } = useGet<LedgerEntry[]>('/api/ledger');
  const champ = reg?.champion;
  const baseline = runs?.find((r) => r.agent === 'v0' && r.split === 'dev' && !r.dry_run && r.summary?.n_scored);
  const champRun = runs?.find((r) => r.run_id === champ?.run_id);
  const cycles = (ledger ?? []).filter((e) => e.kind === 'cycle');
  const promoted = cycles.filter((e) => e.outcome?.verdict === 'promote').length;
  const tokens = cycles.reduce((n, e) => n + Object.values(e.tokens ?? {}).reduce((a, b) => a + b, 0), 0);

  return (
    <>
      <p className="label">DABstep · Claude Agent SDK · Haiku 4.5</p>
      <h1>
        A Haiku agent that <em>learns</em> from the tasks it got wrong
      </h1>
      <p className="lead">
        One stateful Python tool, a system prompt and a helper module. After every scored run a single optimiser session
        reads the failures and the traces, writes the next version, and a gate decides. Everything here is the dev split
        of ten gold tasks — the 450 leaderboard tasks are never scored in this build.
      </p>

      <div className="kpis">
        <div className="kpi">
          <div className="label">champion on dev-10</div>
          <div className={`n ${champ && (champ.passed ?? 0) >= 7 ? 'ok' : 'warn'}`}>
            {champ ? `${champ.passed}/${champ.n_scored}` : '—'}
          </div>
          <div className="b">
            {champ ? `${champ.agent} · ${champ.model}` : 'no champion yet'}
            {baseline?.summary && champ && baseline.agent !== champ.agent ? ` · v0 baseline ${baseline.summary.passed}/${baseline.summary.n_scored}` : ''}
          </div>
        </div>
        <div className="kpi">
          <div className="label">hard tasks</div>
          <div className="n">{champRun?.summary ? `${champRun.summary.hard_passed}/${champRun.summary.hard_n}` : '—'}</div>
          <div className="b">of the 7 hard dev tasks · NVIDIA's Haiku recipe reports 89.95% on the 378 hard leaderboard tasks</div>
        </div>
        <div className="kpi">
          <div className="label">loop cycles</div>
          <div className="n">{cycles.length}</div>
          <div className="b">
            {promoted} promoted · {cycles.length - promoted} held · {fmtK(tokens)} tokens across optimiser + eval
          </div>
        </div>
        <div className="kpi">
          <div className="label">cost to the author</div>
          <div className="n ok">$0</div>
          <div className="b">dev runs bill the Claude subscription; the public demo cannot call a model</div>
        </div>
      </div>

      <h2>1 · The loop — a failure becomes a diagnosis, a diff, and a verdict</h2>
      <ol className="steps">
        <li>
          <span>
            <b>Score</b> the champion on the ten gold tasks with the leaderboard's own scorer. <Link to="/runs">Runs</Link>.
          </span>
        </li>
        <li>
          <span>
            <b>Diagnose</b>: one Agent SDK session (Sonnet) reads every failed trace and the ledger of earlier attempts, and may
            edit only <code>system.md</code> and <code>helper.py</code> of the next version. <Link to="/loop">Loop</Link>.
          </span>
        </li>
        <li>
          <span>
            <b>Gate</b>: the challenger must pass more and flip nothing that passed. <Link to="/compare">Gate</Link>.
          </span>
        </li>
        <li>
          <span>
            <b>Record</b>: the diagnosis and the verdict go to <code>loop/ledger.jsonl</code>, so the next cycle does not retry
            what failed.
          </span>
        </li>
      </ol>

      <h2>2 · Latest cycles — what changed, and whether it held</h2>
      {cycles.length === 0 ? (
        <div className="empty">No cycle has run yet. <code>make loop</code> writes the first ledger entry.</div>
      ) : (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>cycle</th>
                <th>champion → challenger</th>
                <th>verdict</th>
                <th>passes</th>
                <th>fixed</th>
                <th>broken</th>
                <th>prompt</th>
                <th>helper</th>
              </tr>
            </thead>
            <tbody>
              {cycles.map((e) => (
                <tr key={e.cycle}>
                  <td className="num">{e.cycle}</td>
                  <td className="sub">
                    {e.champion} → {e.challenger ?? '—'}
                    {e.outcome?.challenger_run && <span className="path">{shortRun(e.outcome.challenger_run)}</span>}
                  </td>
                  <td>
                    <span className={`status ${e.outcome?.verdict === 'promote' ? 'ok' : e.outcome?.verdict === 'hold' ? 'warn' : 'no'}`}>
                      {e.outcome?.verdict ?? 'pending'}
                    </span>
                  </td>
                  <td className="num">{e.outcome?.passes ?? '—'}</td>
                  <td className="mono">{(e.outcome?.fixed ?? []).join(', ') || '—'}</td>
                  <td className="mono">{(e.outcome?.broken ?? []).join(', ') || '—'}</td>
                  <td className="wrap">{e.prompt_diff_summary || '—'}</td>
                  <td className="wrap">{e.helper_diff_summary || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>3 · What is and is not claimed</h2>
      <div className="cards">
        <div className="card">
          <h3>Scored</h3>
          <p>The ten dev tasks with published answers, using <code>question_scorer</code> vendored verbatim from the benchmark space.</p>
        </div>
        <div className="card">
          <h3>Not scored</h3>
          <p>The 450 leaderboard tasks. No answer key is derived from other teams' submissions; the only gold used is the dev split's.</p>
        </div>
        <div className="card">
          <h3>Replicated</h3>
          <p>NVIDIA's "Data Explorer" shape: Haiku 4.5, one Python executor, a helper module grown from failures, offline reflection.</p>
        </div>
      </div>
    </>
  );
}
