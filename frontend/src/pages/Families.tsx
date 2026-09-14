import { Link, useParams } from 'react-router-dom';
import { shortRun, useGet } from '../lib/api';

type Method = { helper?: string; exists?: boolean; steps?: string[]; manual?: string[] };
type FewShot = { task_id?: string; question?: string; code?: string } | null;
type Card = {
  status: string;
  guidelines?: { guideline: string; n: number; format: string }[];
  canonical_method?: Method;
  conflict_ruling?: string;
  pitfalls?: string[];
  few_shot?: FewShot;
  prompt_rule?: string;
  note?: string;
  evidence?: string[];
  probe_run?: string;
  model?: string;
  history?: { cycle: number; kind: string; run?: string; status?: string }[];
};
type Signals = {
  n: number;
  task_ids: string[];
  s1_modal_share: number | null;
  s1_methods: { signature: string[]; n: number; tasks: string[] }[];
  s2_agreement: number | null;
  s2_disagree: string[];
  s3_checks: { name: string; tasks: string[]; status: string; detail: string }[];
  s3_passed: number;
  s3_failed: number;
  s3_skipped: number;
  s5_compliance: number | null;
  s5_bad: string[];
  turns_mean: number;
  errors: string[];
  answers: Record<string, string>;
};
type Row = {
  id: string;
  name: string;
  pattern: string;
  operation: string;
  invariant: string;
  tasks: number;
  templates: number;
  levels: Record<string, number>;
  dev_anchor: string[];
  status: string;
  card: Card | null;
  signals: Signals | null;
};
type Composite = { families: number; tasks: number; s3_passed: number; s3_failed: number; s3_skipped: number; s1_mean: number | null; s2_mean: number | null; s5_mean: number | null; errors: number };
type FamiliesDoc = {
  families: Row[];
  agreement: { ari: Record<string, number>; boundary_count: number; split_count: number; confusion: Record<string, Record<string, Record<string, number>>> } | null;
  embedding: { model: string; k: number; silhouette: Record<string, number> } | null;
  membership_model: string | null;
  probe: { run_id: string; agent: string; composite: Composite } | null;
  dev_anchored: number;
  with_entry_point: number;
};
type FamilyDoc = Row & {
  templates_list: { template: string; n: number }[];
  members: { task_id: string; question: string; level: string; boundary: string[] }[];
  probe_run: string | null;
  history: { cycle: number; challenger: string | null; verdict: string | null; before: Partial<Signals> | null; after: Partial<Signals> | null }[];
};

const STATUS_CLASS: Record<string, string> = { verified: 'v-ok', provisional: 'v-warn', open: 'v-no', none: 'v-no' };
const STATUS_WORD: Record<string, string> = { verified: '● verified', provisional: '◐ provisional', open: '○ open', none: '○ no card' };

function pct(x: number | null | undefined): string {
  return x == null ? '—' : `${Math.round(x * 100)}%`;
}

export function Families() {
  const { fid } = useParams();
  if (fid) return <Family fid={fid} />;
  return <Index />;
}

function Index() {
  const { data } = useGet<FamiliesDoc>('/api/families');
  const rows = data?.families ?? [];
  const unanchored = rows.filter((r) => r.dev_anchor.length === 0);
  const hardUnanchored = unanchored.reduce((n, r) => n + (r.levels.hard ?? 0), 0);
  const max = Math.max(1, ...rows.map((r) => r.tasks));
  const comp = data?.probe?.composite;
  const statuses = rows.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.status]: (acc[r.status] ?? 0) + 1 }), {});
  return (
    <>
      <p className="label">The 450 by question family · lens 1 of three</p>
      <h1>
        Ten gold answers anchor six of twelve families; the other six are learned <em>without answers</em>
      </h1>
      <p className="lead">
        Every leaderboard task is a permutation of one of 106 templates, and every template needs one of twelve computations. A
        family gets one method, one helper entry point, one prompt rule and one card, written by a reflector that saw the
        agent's probe traces side by side. Nothing on this page reads a gold answer for the 450.
      </p>

      <div className="kpis">
        <div className="kpi">
          <div className="label">families with a dev anchor</div>
          <div className="n">{data ? `${data.dev_anchored}/12` : '—'}</div>
          <div className="b">{hardUnanchored} of 378 hard tasks sit in the {unanchored.length} unanchored families</div>
        </div>
        <div className="kpi">
          <div className="label">cards by status</div>
          <div className="n">{rows.length ? `${statuses.verified ?? 0} · ${statuses.provisional ?? 0} · ${statuses.open ?? 0}` : '—'}</div>
          <div className="b">verified · provisional · open{statuses.none ? ` · ${statuses.none} without a card yet` : ''}</div>
        </div>
        <div className="kpi">
          <div className="label">lens agreement (ARI)</div>
          <div className="n">{data?.agreement ? data.agreement.ari.l1_l3.toFixed(2) : '—'}</div>
          <div className="b">
            {data?.agreement
              ? `regex vs Sonnet membership · vs embeddings ${data.agreement.ari.l1_l2.toFixed(2)} · ${data.agreement.boundary_count}/450 boundary tasks`
              : 'run `dabstep lenses`'}
          </div>
        </div>
        <div className="kpi">
          <div className="label">latest probe, invariants</div>
          <div className={`n ${comp && comp.s3_failed === 0 ? 'ok' : comp ? 'warn' : ''}`}>{comp ? `${comp.s3_passed} / ${comp.s3_failed}` : '—'}</div>
          <div className="b">
            {comp && data?.probe
              ? `passed / failed · ${comp.tasks} tasks · S1 ${pct(comp.s1_mean)} · S2 ${pct(comp.s2_mean)} · S5 ${pct(comp.s5_mean)} · ${data.probe.agent}`
              : 'no probe yet'}
          </div>
        </div>
      </div>

      <h2>1 · Coverage — six hard families have never been checked against gold</h2>
      <figure>
        <div className="label fig-title">fig 1 · the 450 by family · bar = tasks · filled = the family has a dev-10 anchor · amber = its anchor fails</div>
        <svg className="dia" viewBox={`0 0 1000 ${rows.length * 30 + 20}`} role="img" aria-label="One bar per family, sized by how many of the 450 tasks fall in it; filled bars have a dev-10 gold anchor.">
          {rows.map((r, i) => {
            const y = 12 + i * 30;
            const w = Math.round((r.tasks / max) * 520);
            const anchored = r.dev_anchor.length > 0;
            const failing = r.card?.status === 'open' && anchored;
            return (
              <g key={r.id} id={`fam-${r.id}`}>
                <title>{`${r.id} ${r.name}: ${r.tasks} tasks, ${r.templates} templates`}</title>
                <text className="tx" x="0" y={y + 13}>
                  {r.id} {r.name}
                </text>
                <rect className={`bar ${anchored ? (failing ? 'pro' : 'hi') : ''}`} x="300" y={y} width={w} height="18" />
                <text className="tx s" x={308 + w} y={y + 13}>
                  {r.tasks} · {r.templates} tpl{anchored ? ` · dev ${r.dev_anchor.join(', ')}` : ' · no gold'}
                </text>
              </g>
            );
          })}
        </svg>
        <figcaption>
          <b>Counts from <code>loop/families/families.json</code>.</b> A filled bar means at least one dev task exercises the family's
          computation; a hollow one means the agent's method there has only ever been judged without an answer.
        </figcaption>
      </figure>

      <h2>2 · Cards — the method, the entry point, the rule, and how sure the reflector is</h2>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>family</th>
              <th>tasks</th>
              <th>status</th>
              <th>helper entry point</th>
              <th>prompt rule</th>
              <th>S1</th>
              <th>S2</th>
              <th>S3 ✓/✗</th>
              <th>S5</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const m = r.card?.canonical_method;
              const s = r.signals;
              return (
                <tr key={r.id}>
                  <td className="sub">
                    <Link to={`/families/${r.id}`}>{r.id}</Link> {r.name}
                    <span className="path">{r.operation}</span>
                  </td>
                  <td className="num">{r.tasks}</td>
                  <td className={STATUS_CLASS[r.status] ?? ''}>{STATUS_WORD[r.status] ?? r.status}</td>
                  <td>
                    {m?.helper ? <code>{m.helper}</code> : '—'}
                    {m && (
                      <span className="path">{m.exists ? 'exists in the champion' : 'missing: the optimiser adds it'}</span>
                    )}
                  </td>
                  <td className="small">{r.card?.prompt_rule || '—'}</td>
                  <td className="num">{pct(s?.s1_modal_share)}</td>
                  <td className="num">{pct(s?.s2_agreement)}</td>
                  <td className={`num ${s && s.s3_failed > 0 ? 'v-warn' : ''}`}>{s ? `${s.s3_passed}/${s.s3_failed}` : '—'}</td>
                  <td className="num">{pct(s?.s5_compliance)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="insight">
        S1 is the share of probe traces on the family's modal method, S2 the share whose two passes agreed, S3 the invariants
        passed and failed between sibling answers, S5 the share whose answer matched the guideline's format. None needs gold.
      </p>

      {data?.agreement && (
        <>
          <h2>3 · Three lenses — where the regex, the embeddings and Sonnet disagree is where to sample first</h2>
          <div className="chips">
            <span className="chip">embeddings {data.embedding?.model} · k = {data.embedding?.k}</span>
            <span className="chip">membership pass {data.membership_model}</span>
            <span className="chip">ARI regex/embeddings {data.agreement.ari.l1_l2.toFixed(2)}</span>
            <span className="chip">ARI regex/Sonnet {data.agreement.ari.l1_l3.toFixed(2)}</span>
            <span className="chip">ARI embeddings/Sonnet {data.agreement.ari.l2_l3.toFixed(2)}</span>
            <span className="chip warn">{data.agreement.boundary_count} boundary tasks · {data.agreement.split_count} with split membership</span>
          </div>
          <Confusion matrix={data.agreement.confusion.l1_l3} title="fig 2 · regex family (rows) against Sonnet's top cluster (columns) · counts of the 450" />
          <p className="insight">
            A row spread over two columns is a family Sonnet reads as two computations; two rows in one column are families it
            cannot tell apart. Both are boundary cases and the sampler draws them first. Source: <code>loop/families/lenses.json</code>.
          </p>
        </>
      )}
    </>
  );
}

function Confusion({ matrix, title }: { matrix: Record<string, Record<string, number>>; title: string }) {
  const rows = Object.keys(matrix).sort();
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(matrix[r])))).sort();
  const max = Math.max(1, ...rows.flatMap((r) => cols.map((c) => matrix[r][c] ?? 0)));
  return (
    <figure>
      <div className="label fig-title">{title}</div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>family</th>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r}>
                <td className="sub">{r}</td>
                {cols.map((c) => {
                  const v = matrix[r][c] ?? 0;
                  const alpha = v ? 0.15 + (0.7 * v) / max : 0;
                  return (
                    <td key={c} className="num" style={v ? { background: `color-mix(in srgb, var(--accent) ${Math.round(alpha * 100)}%, transparent)` } : undefined}>
                      {v || ''}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}

function Family({ fid }: { fid: string }) {
  const { data: f, error } = useGet<FamilyDoc>(`/api/families/${fid}`);
  if (error) return <div className="empty">{error}</div>;
  if (!f) return <div className="empty">…</div>;
  const c = f.card;
  const s = f.signals;
  const m = c?.canonical_method;
  return (
    <>
      <p className="label">
        <Link to="/families">families</Link> · {f.id}
      </p>
      <h1>
        {f.name}: {f.tasks} of the 450 need <em>{m?.helper ? m.helper.split('(')[0] : 'one method'}</em>
      </h1>
      <p className="lead">{f.operation}. Invariant between siblings: {f.invariant}.</p>

      <div className="kpis">
        <div className="kpi">
          <div className="label">status</div>
          <div className={`n ${c?.status === 'verified' ? 'ok' : c?.status === 'provisional' ? 'warn' : ''}`}>{STATUS_WORD[c?.status ?? 'none']}</div>
          <div className="b">{c?.probe_run ? `card from probe ${shortRun(c.probe_run)} · ${c.model}` : 'no card yet: run `dabstep ureflect`'}</div>
        </div>
        <div className="kpi">
          <div className="label">dev anchor</div>
          <div className="n">{f.dev_anchor.length ? f.dev_anchor.join(', ') : 'none'}</div>
          <div className="b">{f.dev_anchor.length ? 'gold exists for these dev tasks' : 'never checked against gold'}</div>
        </div>
        <div className="kpi">
          <div className="label">entry point</div>
          <div className={`n ${m?.exists ? 'ok' : m ? 'warn' : ''}`}>{m ? (m.exists ? 'exists' : 'missing') : '—'}</div>
          <div className="b">{m?.helper ? <code>{m.helper}</code> : 'the reflector names it'}</div>
        </div>
        <div className="kpi">
          <div className="label">latest probe</div>
          <div className={`n ${s && s.s3_failed ? 'warn' : ''}`}>{s ? `${s.n} tasks` : '—'}</div>
          <div className="b">{s ? `S1 ${pct(s.s1_modal_share)} · S2 ${pct(s.s2_agreement)} · S3 ${s.s3_passed}/${s.s3_failed}/${s.s3_skipped} · S5 ${pct(s.s5_compliance)} · ${s.turns_mean} turns` : 'no probe yet'}</div>
        </div>
      </div>

      {c?.guidelines?.length ? (
        <>
          <h2>0 · The answer contract — the guidelines these {f.tasks} tasks carry, verbatim</h2>
          <ul>
            {c.guidelines.map((g) => (
              <li key={g.guideline} className="small">
                <span className="num">{g.n}×</span> <code>{g.format}</code> {g.guideline}
              </li>
            ))}
          </ul>
          <p className="insight">
            The guideline outranks the question's wording: it fixes the rounding, the list shape, the sort order and when an
            empty string or "Not Applicable" is right. The routing row's answer format quotes it.
          </p>
        </>
      ) : null}
      {c && (
        <>
          <h2>1 · The card — what the next optimiser is told</h2>
          <dl className="diff-sum">
            <dt>method</dt>
            <dd>
              {m?.helper && <code>{m.helper}</code>}
              {m?.steps?.length ? (
                <ol>
                  {m.steps.map((st, i) => (
                    <li key={i}>{st}</li>
                  ))}
                </ol>
              ) : null}
              {m?.manual?.length ? <span className="small">manual: {m.manual.join(' · ')}</span> : null}
            </dd>
            <dt>prompt rule</dt>
            <dd>{c.prompt_rule || '—'}</dd>
            {c.conflict_ruling && (
              <>
                <dt>ruling</dt>
                <dd>{c.conflict_ruling}</dd>
              </>
            )}
            {c.pitfalls?.length ? (
              <>
                <dt>pitfalls</dt>
                <dd>
                  <ul>
                    {c.pitfalls.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </dd>
              </>
            ) : null}
            <dt>few-shot</dt>
            <dd>{c.few_shot?.code ? <code>{c.few_shot.code}</code> : 'none qualified'}</dd>
            {c.note && (
              <>
                <dt>note</dt>
                <dd>{c.note}</dd>
              </>
            )}
            <dt>evidence</dt>
            <dd className="small">{(c.evidence ?? []).join(' · ') || '—'}</dd>
          </dl>
        </>
      )}

      {s && (
        <>
          <h2>2 · The probe — what the agent actually did on {s.n} of these tasks</h2>
          <h3>Methods (S1)</h3>
          <ul>
            {s.s1_methods.map((mm, i) => (
              <li key={i} className="small">
                {mm.n}× <code>{mm.signature.join(', ') || 'no helper call'}</code> ← {mm.tasks.join(', ')}
              </li>
            ))}
          </ul>
          {s.s3_checks.length > 0 && (
            <>
              <h3>Invariants (S3)</h3>
              <div className="tw">
                <table>
                  <thead>
                    <tr>
                      <th>check</th>
                      <th>tasks</th>
                      <th>status</th>
                      <th>detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.s3_checks.map((ch, i) => (
                      <tr key={i}>
                        <td>{ch.name}</td>
                        <td className="num">
                          {ch.tasks.map((t) => (
                            <span key={t}>
                              {f.probe_run ? <Link to={`/runs/${f.probe_run}/traces/${t}`}>{t}</Link> : t}{' '}
                            </span>
                          ))}
                        </td>
                        <td className={ch.status === 'passed' ? 'v-ok' : ch.status === 'failed' ? 'v-warn' : 'v-no'}>{ch.status}</td>
                        <td className="small">{ch.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {(s.s2_disagree.length > 0 || s.s5_bad.length > 0) && (
            <div className="chips">
              {s.s2_disagree.length > 0 && <span className="chip warn">passes disagreed: {s.s2_disagree.join(', ')}</span>}
              {s.s5_bad.length > 0 && <span className="chip warn">format broke: {s.s5_bad.join(', ')}</span>}
            </div>
          )}
        </>
      )}

      {f.history.length > 0 && (
        <>
          <h2>3 · Across cycles — the paired signals, champion against challenger</h2>
          <div className="tw">
            <table>
              <thead>
                <tr>
                  <th>cycle</th>
                  <th>challenger</th>
                  <th>verdict</th>
                  <th>S1</th>
                  <th>S2</th>
                  <th>S3 ✓/✗</th>
                  <th>S5</th>
                  <th>turns</th>
                </tr>
              </thead>
              <tbody>
                {f.history.map((h) => (
                  <tr key={h.cycle} className={h.verdict === 'promote' ? 'pro' : ''}>
                    <td className="num">{h.cycle}</td>
                    <td className="sub">{h.challenger}</td>
                    <td className={h.verdict === 'promote' ? 'v-ok' : 'v-warn'}>{h.verdict}</td>
                    <td className="num">{pct(h.before?.s1_modal_share)} → {pct(h.after?.s1_modal_share)}</td>
                    <td className="num">{pct(h.before?.s2_agreement)} → {pct(h.after?.s2_agreement)}</td>
                    <td className="num">
                      {h.before?.s3_passed ?? '—'}/{h.before?.s3_failed ?? '—'} → {h.after?.s3_passed ?? '—'}/{h.after?.s3_failed ?? '—'}
                    </td>
                    <td className="num">{pct(h.before?.s5_compliance)} → {pct(h.after?.s5_compliance)}</td>
                    <td className="num">{h.before?.turns_mean ?? '—'} → {h.after?.turns_mean ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>{f.history.length ? 4 : 3} · Members — {f.templates} templates over {f.tasks} tasks</h2>
      <ul>
        {f.templates_list.map((t) => (
          <li key={t.template} className="small">
            <span className="num">{t.n}×</span> {t.template}
          </li>
        ))}
      </ul>
      <details>
        <summary className="small">every member ({f.members.length}) · boundary tasks marked</summary>
        <ul>
          {f.members.map((t) => (
            <li key={t.task_id} className="small">
              <Link to={`/tasks?id=${t.task_id}`}>{t.task_id}</Link> {t.question}
              {t.boundary.length ? <span className="chip warn" style={{ marginLeft: 'var(--s2)' }}>boundary</span> : null}
            </li>
          ))}
        </ul>
      </details>
      <p className="small" style={{ marginTop: 'var(--s5)' }}>
        The card is <code>loop/families/{f.id}.json</code>; the probe run it cites is on the <Link to="/runs">Runs</Link> page.
      </p>
    </>
  );
}
