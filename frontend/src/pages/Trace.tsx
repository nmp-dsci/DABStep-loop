import { Link, useParams } from 'react-router-dom';
import { type Event, fmtS, useGet } from '../lib/api';

type TracePayload = { task_id: string; agent_answer: string; n_turns: number; duration_ms: number; input_tokens: number; output_tokens: number; error: string | null; terminal_reason: string | null; model: string; events: Event[]; raw: { role: string; content: unknown }[] };

export function EventList({ events }: { events: Event[] }) {
  return (
    <>
      {events.map((e, i) => (
        <div key={i} className={`ev ${e.type}`}>
          <div className="label">
            {e.type === 'tool_use' ? 'execute_python' : e.type === 'tool_result' ? (e.is_error ? 'output · error' : 'output') : e.type === 'final' ? 'final answer' : e.type}
          </div>
          {e.type === 'tool_use' && <pre>{String(e.code)}</pre>}
          {e.type === 'tool_result' && <pre>{String(e.text)}</pre>}
          {e.type === 'text' && <pre>{String(e.text)}</pre>}
          {e.type === 'decline' && <p>{String(e.text)}</p>}
          {e.type === 'final' && (
            <pre>
              {JSON.stringify({ agent_answer: e.agent_answer }, null, 0)}
              {'\n'}
              {`${e.n_turns} turns · ${fmtS(e.duration_ms as number)} · ${e.model} · ${e.terminal_reason}${e.error ? ` · ${e.error}` : ''}`}
            </pre>
          )}
          {e.type === 'start' && <pre>{JSON.stringify(e)}</pre>}
        </div>
      ))}
    </>
  );
}

export function Trace() {
  const { runId = '', taskId = '' } = useParams();
  const { data, error } = useGet<TracePayload>(`/api/runs/${runId}/traces/${taskId}`);
  if (error) return <div className="empty">{error}</div>;
  if (!data) return <p className="muted">loading…</p>;
  const system = data.raw.find((m) => m.role === 'system');
  const user = data.raw.find((m) => m.role === 'user');
  return (
    <>
      <p className="label">
        <Link to="/runs">runs</Link> / <Link to={`/runs/${runId}`}>{runId.replace(/^\d{8}T\d{6}Z_/, '')}</Link> / task {taskId}
      </p>
      <h1>
        Task {taskId}: <em>{data.n_turns} turns</em> to "{data.agent_answer.slice(0, 60)}"
      </h1>
      <p className="lead">
        {data.model} · {fmtS(data.duration_ms)} · {data.input_tokens.toLocaleString()} tokens in, {data.output_tokens.toLocaleString()} out ·{' '}
        {data.terminal_reason}
        {data.error ? ` · ${data.error}` : ''}
      </p>
      <details>
        <summary>system prompt and task prompt, as sent</summary>
        <div className="code">
          <pre>{String(system?.content ?? '')}</pre>
        </div>
        <div className="code">
          <pre>{String(user?.content ?? '')}</pre>
        </div>
      </details>
      <h2>Tool calls and outputs, in order</h2>
      <EventList events={data.events} />
    </>
  );
}
