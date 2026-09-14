import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { type Event, type Health, useGet } from '../lib/api';
import { EventList } from './Trace';

type Pack = { run_id: string | null; agent: string | null; model: string | null; items: { task_id: string; level: string; question: string; gold: string; agent_answer: string; correct: boolean | null }[] };

export function Ask() {
  const health = useOutletContext<Health | null>();
  const demo = health?.mode === 'demo';
  const { data: pack } = useGet<Pack>('/api/demo/pack');
  const [question, setQuestion] = useState('');
  const [guidelines, setGuidelines] = useState('');
  const [events, setEvents] = useState<Event[]>([]);
  const [busy, setBusy] = useState(false);

  async function run(q = question, g = guidelines) {
    if (!q.trim() || busy) return;
    setBusy(true);
    setEvents([]);
    try {
      const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, guidelines: g }) });
      if (!r.ok || !r.body) throw new Error(`${r.status}`);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() ?? '';
        for (const p of parts) {
          const line = p.split('\n').find((l) => l.startsWith('data:'));
          if (line) setEvents((ev) => [...ev, JSON.parse(line.slice(5).trim()) as Event]);
        }
      }
    } catch (e) {
      setEvents((ev) => [...ev, { type: 'error', text: String(e) }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="label">The agent, live</p>
      <h1>
        Ask the champion — {demo ? <>a <em>recorded</em> session replays</> : <>a <em>live</em> session streams</>}
      </h1>
      <p className="lead">
        {demo
          ? `This deployment has no model and no key. It replays the champion's recorded answers to the ten dev questions — the same tool calls, at a readable pace — and declines anything else.`
          : `Dev mode: this starts a real Agent SDK session on the registry's champion, billed to the subscription, and streams every tool call as it happens.`}
      </p>
      {pack?.items.length ? (
        <>
          <h2>1 · Pick a question the champion has answered — {pack.agent} · {pack.model}</h2>
          <div className="tw">
            <table>
              <thead>
                <tr>
                  <th>task</th>
                  <th>level</th>
                  <th>question</th>
                  <th>recorded</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {pack.items.map((it) => (
                  <tr key={it.task_id}>
                    <td className="sub num">{it.task_id}</td>
                    <td>{it.level}</td>
                    <td className="q wrap">{it.question}</td>
                    <td>{it.correct ? <span className="status ok">pass</span> : <span className="status err">fail</span>}</td>
                    <td>
                      <button className="linkbtn" disabled={busy} onClick={() => { setQuestion(it.question); setGuidelines(''); void run(it.question, ''); }}>
                        {demo ? 'replay' : 'ask live'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
      <h2>2 · Or type one</h2>
      <form onSubmit={(e) => { e.preventDefault(); void run(); }}>
        <div className="row">
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Which issuing country has the highest number of transactions?" aria-label="question" />
        </div>
        <div className="row">
          <input type="text" value={guidelines} onChange={(e) => setGuidelines(e.target.value)} placeholder="guidelines (optional): answer format" aria-label="guidelines" />
        </div>
        <div className="row">
          <button className="btn" type="submit" disabled={busy || !question.trim()}>
            {busy ? 'running…' : demo ? 'replay' : 'ask the champion'}
          </button>
          {demo && <span className="small muted">Unlisted questions are declined: nothing here can reach a model.</span>}
        </div>
      </form>
      {events.length > 0 && (
        <>
          <h2>3 · The session</h2>
          <EventList events={events} />
        </>
      )}
    </>
  );
}
