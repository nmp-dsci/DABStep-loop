import { Link } from 'react-router-dom';

function Arrow() {
  return (
    <defs>
      <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 0L10 5L0 10z" fill="currentColor" />
      </marker>
    </defs>
  );
}

export function Architecture() {
  return (
    <>
      <p className="label">System</p>
      <h1>
        Five planes, and only <em>two</em> files the loop is allowed to change
      </h1>
      <p className="lead">
        The agent is small on purpose: a system prompt, a helper module and one tool. Everything around it — the scorer, the
        run folders, the tracker, the gate, the ledger — exists so that a change to those two files can be measured and kept or
        thrown away.
      </p>

      <h2>1 · The planes — data in, a scored run folder out</h2>
      <figure>
        <div className="label fig-title">fig 1 · the five planes</div>
        <svg className="dia" viewBox="0 0 1000 420" role="img" aria-label="Five planes: data, agent, evaluation, tracking, loop. Data feeds the agent; the agent produces a run folder; evaluation scores it; tracking indexes it; the loop reads failures and writes the next agent version.">
          <Arrow />
          <g id="data">
            <title>Data plane</title>
            <rect className="nd" x="20" y="40" width="180" height="120" rx="10" />
            <text className="tx k" x="36" y="64">data</text>
            <text className="tx" x="36" y="90">payments.csv · fees.json</text>
            <text className="tx s" x="36" y="112">manual.md · merchants</text>
            <text className="tx s" x="36" y="134">tasks/dev.jsonl (10 gold)</text>
          </g>
          <g id="agent">
            <title>Agent plane</title>
            <rect className="nd hi" x="260" y="40" width="220" height="120" rx="10" />
            <text className="tx k" x="276" y="64">agent · agents/vN</text>
            <text className="tx" x="276" y="90">system.md · helper.py</text>
            <text className="tx s" x="276" y="112">Haiku 4.5 · ≤20 turns · 270s</text>
            <text className="tx s" x="276" y="134">one tool: execute_python</text>
          </g>
          <g id="eval">
            <title>Evaluation plane</title>
            <rect className="nd" x="540" y="40" width="200" height="120" rx="10" />
            <text className="tx k" x="556" y="64">eval · runs/&lt;id&gt;</text>
            <text className="tx" x="556" y="90">question_scorer (vendored)</text>
            <text className="tx s" x="556" y="112">results.jsonl · traces/</text>
            <text className="tx s" x="556" y="134">submission.jsonl</text>
          </g>
          <g id="tracking">
            <title>Tracking plane</title>
            <rect className="nd" x="800" y="40" width="180" height="120" rx="10" />
            <text className="tx k" x="816" y="64">tracking</text>
            <text className="tx" x="816" y="90">MLflow 3 · central</text>
            <text className="tx s" x="816" y="112">nmp-central-ai :5000</text>
            <text className="tx s" x="816" y="134">registry.json aliases</text>
          </g>
          <g id="loop">
            <title>Loop plane</title>
            <rect className="nd hi" x="260" y="250" width="480" height="130" rx="10" />
            <text className="tx k" x="276" y="274">loop · one optimiser session</text>
            <text className="tx" x="276" y="300">reads: failed traces + ledger history</text>
            <text className="tx" x="276" y="322">writes: agents/v(N+1)/system.md, helper.py, diagnosis.json</text>
            <text className="tx s" x="276" y="344">gate: one-sided McNemar, p &lt; 0.05</text>
            <text className="tx s" x="276" y="366">ledger: loop/ledger.jsonl (committed)</text>
          </g>
          <g id="viewer">
            <title>Viewer</title>
            <rect className="nd ext" x="800" y="250" width="180" height="130" rx="10" />
            <text className="tx k" x="816" y="274">viewer</text>
            <text className="tx s" x="816" y="300">FastAPI + React</text>
            <text className="tx s" x="816" y="322">reads run folders</text>
            <text className="tx s" x="816" y="344">demo: replay only</text>
          </g>
          <path className="ed" d="M200 100 L258 100" />
          <path className="ed" d="M480 100 L538 100" />
          <path className="ed" d="M740 100 L798 100" />
          <path className="ed hi" d="M640 160 L640 248" />
          <text className="cap" x="650" y="210">failures</text>
          <path className="ed hi" d="M370 250 L370 162" />
          <text className="cap" x="380" y="210">v(N+1)</text>
          <path className="ed dash" d="M740 315 L798 315" />
        </svg>
        <figcaption>
          The loop only touches the agent plane, and only through a new version folder — a run is never edited after it is scored.
          <span className="path">src/dabstep_loop/{'{'}agent,eval,tracking,loop{'}'}</span>
        </figcaption>
      </figure>

      <h2>2 · One cycle — diagnose, rewrite, evaluate, gate, record</h2>
      <figure>
        <div className="label fig-title">fig 2 · a loop cycle</div>
        <svg className="dia" viewBox="0 0 1000 250" role="img" aria-label="A loop cycle from the champion run through the optimiser session, the challenger run, the gate and the ledger, with the ledger feeding back into the next optimiser session.">
          <Arrow />
          {[
            ['champion run', 'runs/…_vN_dev', 20],
            ['optimiser', 'Sonnet · 1 session', 215],
            ['challenger', 'agents/v(N+1)', 410],
            ['challenger run', 'runs/…_v(N+1)_dev', 605],
            ['gate', 'compare.py', 800],
          ].map(([t, s, x], i) => (
            <g key={t} id={`step-${i}`}>
              <title>{t}</title>
              <rect className={`nd ${i === 1 || i === 4 ? 'hi' : ''}`} x={x} y="60" width="170" height="70" rx="10" />
              <text className="tx" x={Number(x) + 16} y="90">{t}</text>
              <text className="tx s" x={Number(x) + 16} y="112">{s}</text>
            </g>
          ))}
          <path className="ed" d="M190 95 L213 95" />
          <path className="ed" d="M385 95 L408 95" />
          <path className="ed" d="M580 95 L603 95" />
          <path className="ed" d="M775 95 L798 95" />
          <g id="ledger">
            <title>Ledger</title>
            <rect className="nd" x="410" y="180" width="365" height="50" rx="10" />
            <text className="tx" x="426" y="210">loop/ledger.jsonl · diagnoses + verdict, per cycle</text>
          </g>
          <path className="ed" d="M885 130 L885 205 L777 205" />
          <path className="ed dash" d="M408 205 L300 205 L300 132" />
          <text className="cap" x="310" y="170">history for the next cycle</text>
        </svg>
        <figcaption>
          The optimiser learns across cycles only through the ledger it is shown; a change that held is recorded next to one that
          did not.
          <span className="path">src/dabstep_loop/loop/{'{'}run,optimiser,ledger{'}'}.py</span>
        </figcaption>
      </figure>

      <h2>3 · The agent — what Haiku is given, and what it may do</h2>
      <div className="grid2">
        <div className="card">
          <h3>Per task</h3>
          <p>
            System prompt from <code>system.md</code>; a user prompt with the file structures, the helper's signatures, the question
            and its guidelines. Twenty turns, 270 seconds, one tool. The last message must be <code>{'{"agent_answer": …}'}</code>.
          </p>
        </div>
        <div className="card">
          <h3>The tool</h3>
          <p>
            <code>execute_python</code>: a persistent namespace with pandas preloaded and <code>helper</code> importable, a 120s
            limit per call, and a loop-breaker that refuses the third identical call. In-process, via the Agent SDK's MCP server.
          </p>
        </div>
        <div className="card">
          <h3>Billing</h3>
          <p>
            Dev sessions run on the Claude subscription; the child process has <code>ANTHROPIC_API_KEY</code> blanked and{' '}
            <code>CLAUDE_CODE_*</code> stripped. The demo image sets <code>DEMO_MODE=1</code> in the Dockerfile and raises before any
            model call.
          </p>
        </div>
        <div className="card">
          <h3>Versions</h3>
          <p>
            A version is a folder; its fingerprint is the hash of its three files. See <Link to="/agents">Agents</Link> for every
            version and the diagnosis that produced it.
          </p>
        </div>
      </div>
    </>
  );
}
