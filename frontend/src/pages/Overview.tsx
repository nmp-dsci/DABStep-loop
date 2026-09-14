import { Link } from 'react-router-dom';
import { type LedgerEntry, type Registry, type RunMeta, type TaskResult, fmtK, shortRun, useGet } from '../lib/api';

function Arrow() {
  return (
    <defs>
      <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 0L10 5L0 10z" fill="currentColor" />
      </marker>
    </defs>
  );
}

export function Overview() {
  const { data: reg } = useGet<Registry>('/api/registry');
  const { data: runs } = useGet<RunMeta[]>('/api/runs');
  const { data: ledger } = useGet<LedgerEntry[]>('/api/ledger');
  const champ = reg?.champion;
  const baseline = runs?.find((r) => r.agent === 'v0' && r.split === 'dev' && !r.dry_run && r.summary?.n_scored);
  const cycles = (ledger ?? []).filter((e) => e.kind === 'cycle');
  const reflections = (ledger ?? []).filter((e) => e.kind === 'reflect');
  const promoted = cycles.filter((e) => e.outcome?.verdict === 'promote').length;
  const best = runs?.filter((r) => r.split === 'dev' && r.summary?.n_scored).sort((a, b) => (b.summary?.passed ?? 0) - (a.summary?.passed ?? 0))[0];
  const optTokens = cycles.reduce((n, e) => n + (e.tokens?.optimiser_in ?? 0) + (e.tokens?.optimiser_out ?? 0), 0);
  const { data: champDetail } = useGet<{ results: TaskResult[] }>(champ ? `/api/runs/${champ.run_id}` : null);
  const champRun = champDetail
    ? {
        n: champDetail.results.length,
        in: champDetail.results.reduce((n, r) => n + r.input_tokens, 0),
        out: champDetail.results.reduce((n, r) => n + r.output_tokens, 0),
        turns: champDetail.results.reduce((n, r) => n + r.n_turns, 0),
        results_tokens: champDetail.results.reduce((n, r) => n + r.input_tokens + r.output_tokens, 0),
      }
    : null;

  return (
    <>
      <p className="label">DABstep · Claude Agent SDK · Haiku 4.5</p>
      <h1>
        A small agent, and the loop that <em>learns</em> from what it got wrong
      </h1>
      <p className="lead">
        The agent is a system prompt, a helper module and one Python tool on Haiku 4.5. The loop around it is one
        optimiser session per cycle that reads every failed trace, edits those two files, and hands the result to a gate.
        Every diagnosis and every verdict is kept, so the next cycle starts from what the last one learnt.
      </p>

      <div className="kpis">
        <div className="kpi">
          <div className="label">champion on dev-10</div>
          <div className="n">{champ ? `${champ.passed}/${champ.n_scored}` : '—'}</div>
          <div className="b">{champ ? `${champ.agent} · ${champ.model}` : 'no champion yet'}{baseline?.summary && champ && baseline.agent !== champ.agent ? ` · v0 baseline ${baseline.summary.passed}/${baseline.summary.n_scored}` : ''}</div>
        </div>
        <div className="kpi">
          <div className="label">best challenger</div>
          <div className={`n ${best && best.agent !== champ?.agent ? 'warn' : ''}`}>{best?.summary ? `${best.summary.passed}/${best.summary.n_scored}` : '—'}</div>
          <div className="b">{best ? (best.agent === champ?.agent ? 'is the champion' : `${best.agent} · held by the gate`) : '—'}</div>
        </div>
        <div className="kpi">
          <div className="label">loop cycles</div>
          <div className="n">{cycles.length}</div>
          <div className="b">{promoted} promoted · {cycles.length - promoted} held · {reflections.length} reflection{reflections.length === 1 ? '' : 's'} · {fmtK(optTokens)} optimiser tokens</div>
        </div>
        <div className="kpi">
          <div className="label">tokens per question</div>
          <div className="n">{champRun ? fmtK(Math.round(champRun.results_tokens / champRun.n)) : '—'}</div>
          <div className="b">
            {champRun ? `${champ?.agent} on dev-10 · ${fmtK(champRun.in)} in / ${fmtK(champRun.out)} out over ${champRun.n} tasks · ${champRun.turns} turns` : '—'}
          </div>
        </div>
      </div>

      <h2>1 · The agent — one session per task, one tool, two files that can change</h2>
      <figure>
        <div className="label fig-title">fig 1 · a task session</div>
        <svg className="dia" viewBox="0 0 1000 330" role="img" aria-label="A task session: the prompt is assembled from the version's system.md, the file structures, the helper's signatures and the question; Haiku 4.5 calls execute_python up to twenty times against a persistent namespace with pandas and the helper loaded; the final message is parsed and scored.">
          <Arrow />
          <g id="prompt">
            <title>Prompt assembly</title>
            <rect className="nd" x="20" y="30" width="230" height="200" rx="10" />
            <text className="tx k" x="36" y="54">prompt</text>
            <text className="tx" x="36" y="82">system.md</text>
            <text className="tx s" x="36" y="102">agents/vN — editable</text>
            <text className="tx" x="36" y="130">task prompt</text>
            <text className="tx s" x="36" y="150">file structures · helper signatures</text>
            <text className="tx s" x="36" y="170">question · guidelines</text>
            <text className="tx s" x="36" y="204">≤ 20 turns · 270 s</text>
          </g>
          <g id="model">
            <title>The model</title>
            <rect className="nd hi" x="320" y="70" width="200" height="110" rx="10" />
            <text className="tx k" x="336" y="94">haiku 4.5</text>
            <text className="tx" x="336" y="122">Agent SDK session</text>
            <text className="tx s" x="336" y="144">no built-in tools</text>
            <text className="tx s" x="336" y="164">one MCP tool allowed</text>
          </g>
          <g id="tool">
            <title>The executor</title>
            <rect className="nd" x="600" y="30" width="230" height="200" rx="10" />
            <text className="tx k" x="616" y="54">execute_python</text>
            <text className="tx" x="616" y="82">persistent namespace</text>
            <text className="tx s" x="616" y="102">pd preloaded · 120 s per call</text>
            <text className="tx" x="616" y="130">helper.py</text>
            <text className="tx s" x="616" y="150">agents/vN — editable</text>
            <text className="tx s" x="616" y="184">loop-breaker: third identical</text>
            <text className="tx s" x="616" y="204">call returns "answer now"</text>
          </g>
          <g id="answer">
            <title>Answer and score</title>
            <rect className="nd" x="320" y="230" width="200" height="80" rx="10" />
            <text className="tx k" x="336" y="254">answer</text>
            <text className="tx s" x="336" y="278">{'{"agent_answer": …}'}</text>
            <text className="tx s" x="336" y="298">→ question_scorer vs gold</text>
          </g>
          <g id="data">
            <title>The data</title>
            <rect className="nd ext" x="870" y="70" width="110" height="110" rx="10" />
            <text className="tx k" x="884" y="94">data/</text>
            <text className="tx s" x="884" y="122">payments</text>
            <text className="tx s" x="884" y="142">fees · manual</text>
            <text className="tx s" x="884" y="162">merchants</text>
          </g>
          <path className="ed" d="M250 125 L318 125" />
          <path className="ed" d="M520 105 L598 105" />
          <text className="cap" x="530" y="96">code</text>
          <path className="ed" d="M598 150 L522 150" />
          <text className="cap" x="530" y="170">output</text>
          <path className="ed dash" d="M830 125 L868 125" />
          <path className="ed hi" d="M420 180 L420 228" />
        </svg>
        <figcaption>
          The two boxes marked editable are the only surfaces the loop may change; the budgets in <code>agent.yaml</code> are frozen so a comparison between versions is a comparison of prompt and helper, not of turns.
          <span className="path">src/dabstep_loop/agent/{'{'}session,prompt,tools/python_executor{'}'}.py · agents/vN/</span>
        </figcaption>
      </figure>

      <h2>2 · The learning loop — a failed trace becomes a diagnosis, a diff, and a verdict</h2>
      <figure>
        <div className="label fig-title">fig 2 · one cycle, and what feeds the next</div>
        <svg className="dia" viewBox="0 0 1000 360" role="img" aria-label="The loop: the champion's scored run yields failed traces; one optimiser session reads them with the ledger history and writes the next version's system.md and helper.py plus a diagnosis; the challenger is scored; the gate promotes when a one-sided McNemar test on the paired tasks clears p < 0.05; the outcome is written back to the ledger, which the next optimiser and the reflection pass both read.">
          <Arrow />
          {[
            ['champion run', 'dev-10 · traces', 20, 'nd'],
            ['failures', 'wrong or errored', 215, 'nd warn'],
            ['optimiser', 'Sonnet · one session', 410, 'nd hi'],
            ['challenger v(N+1)', 'system.md · helper.py', 605, 'nd'],
            ['gate', 'McNemar · p < 0.05', 800, 'nd hi'],
          ].map(([t, s, x, cls], i) => (
            <g key={t} id={`loop-${i}`}>
              <title>{t}</title>
              <rect className={String(cls)} x={x} y="60" width="175" height="70" rx="10" />
              <text className="tx" x={Number(x) + 14} y="90">{t}</text>
              <text className="tx s" x={Number(x) + 14} y="112">{s}</text>
            </g>
          ))}
          <path className="ed" d="M195 95 L213 95" />
          <path className="ed" d="M390 95 L408 95" />
          <path className="ed" d="M585 95 L603 95" />
          <path className="ed" d="M780 95 L798 95" />
          <g id="ledger">
            <title>The ledger</title>
            <rect className="nd" x="215" y="200" width="560" height="70" rx="10" />
            <text className="tx k" x="231" y="224">loop/ledger.jsonl</text>
            <text className="tx" x="231" y="250">diagnoses · change summaries · verdict · fixed / broken / still failed · reflection notes</text>
          </g>
          <g id="reflect">
            <title>Reflection</title>
            <rect className="nd ext" x="800" y="200" width="175" height="70" rx="10" />
            <text className="tx k" x="814" y="224">reflect</text>
            <text className="tx s" x="814" y="250">read-only review of traces</text>
          </g>
          <path className="ed" d="M887 130 L887 170 L887 198" />
          <path className="ed" d="M798 235 L777 235" />
          <path className="ed hi" d="M497 200 L497 132" />
          <text className="cap" x="507" y="172">history: do not repeat</text>
          <path className="ed dash" d="M887 60 L887 20 L107 20 L107 58" />
          <text className="cap" x="380" y="14">promote → new champion · hold → next cycle starts from the held work</text>
          <text className="cap" x="20" y="312">the optimiser may write only agents/v(N+1)/ — a hook denies other paths,</text>
          <text className="cap" x="20" y="334">a checksum of the guarded tree is compared after the session, agent.yaml must be byte-identical</text>
        </svg>
        <figcaption>
          The optimiser learns across cycles only through the ledger it is shown. A held challenger is not discarded: its folder stays, and the next session is told what it fixed and what it broke.
          <span className="path">src/dabstep_loop/loop/{'{'}run,optimiser,ledger,reflect{'}'}.py</span>
        </figcaption>
      </figure>

      <h2>3 · What each cycle did — {cycles.length ? `${cycles.length} cycle${cycles.length === 1 ? '' : 's'}, ${promoted} promoted` : 'none yet'}</h2>
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
                <th>what changed</th>
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
                    <span className={`status ${e.outcome?.verdict === 'promote' ? 'ok' : e.outcome?.verdict === 'hold' ? 'warn' : 'no'}`}>{e.outcome?.verdict ?? 'pending'}</span>
                    {e.outcome?.reason && <span className="path">{e.outcome.reason}</span>}
                  </td>
                  <td className="num">{e.outcome?.passes ?? '—'}</td>
                  <td className="mono">{(e.outcome?.fixed ?? []).join(', ') || '—'}</td>
                  <td className="mono">{(e.outcome?.broken ?? []).join(', ') || '—'}</td>
                  <td className="wrap small">
                    <b>prompt</b> {e.prompt_diff_summary || '—'}
                    <br />
                    <b>helper</b> {e.helper_diff_summary || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reflections.length > 0 && (
        <div className="cards">
          {reflections.map((r) => (
            <div className="card" key={r.cycle}>
              <h3>reflection {r.cycle} on {r.champion} — {r.notes?.length ?? 0} notes for the next optimiser</h3>
              <p>{r.summary}</p>
              <p className="small">
                <Link to="/loop">Read the notes in the ledger</Link>
              </p>
            </div>
          ))}
        </div>
      )}

      <h2>4 · What is and is not claimed</h2>
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
          <p>NVIDIA's "Data Explorer" shape: Haiku 4.5, one Python executor, a helper grown from failures, offline reflection — 89.95% hard on the leaderboard with that recipe, against 19.84% for a plain Sonnet 4 ReAct baseline.</p>
        </div>
      </div>
    </>
  );
}
