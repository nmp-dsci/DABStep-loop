import { Link, useParams } from 'react-router-dom';
import { type AgentInfo, type Registry, shortRun, useGet } from '../lib/api';

type AgentsPayload = { versions: AgentInfo[]; registry: Registry };
type AgentFiles = { name: string; fingerprint: string; config: Record<string, unknown>; files: Record<string, string> };

export function Agents() {
  const { name } = useParams();
  const { data } = useGet<AgentsPayload>('/api/agents');
  const { data: files } = useGet<AgentFiles>(name ? `/api/agents/${name}` : null);
  const champ = data?.registry.champion?.agent;
  const chall = data?.registry.challenger?.agent;

  return (
    <>
      <p className="label">Versions</p>
      <h1>
        Every version is a folder; the champion is the one the <em>gate</em> kept
      </h1>
      <p className="lead">
        <code>agents/vN/</code> holds a system prompt, a helper module and a frozen config. The optimiser writes the next folder and
        a <code>diagnosis.json</code> beside it; the gate decides which folder the registry points at.
      </p>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>version</th>
              <th>role</th>
              <th>fingerprint</th>
              <th>model</th>
              <th>helper functions</th>
              <th>runs</th>
            </tr>
          </thead>
          <tbody>
            {data?.versions.map((v) => (
              <tr key={v.name} className={v.name === champ ? 'pro' : ''}>
                <td className="sub">
                  <Link to={`/agents/${v.name}`}>{v.name}</Link>
                </td>
                <td>
                  {v.name === champ ? <span className="status ok">champion</span> : v.name === chall ? <span className="status warn">challenger</span> : <span className="status no">held</span>}
                </td>
                <td className="mono">{v.fingerprint}</td>
                <td className="mono">{String(v.config.model)}</td>
                <td className="wrap mono small">{v.helper_functions.join(', ') || '—'}</td>
                <td className="small">
                  {v.runs.map((r) => (
                    <div key={r}>
                      <Link to={`/runs/${r}`}>{shortRun(r)}</Link>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {name && files && (
        <>
          <h2>{name} — the files, verbatim</h2>
          {Object.entries(files.files).map(([fname, text]) => (
            <details key={fname} open={fname !== 'agent.yaml'}>
              <summary>
                {fname} <span className="muted small">({text.length.toLocaleString()} chars)</span>
              </summary>
              <div className="code">
                <pre>{text}</pre>
              </div>
            </details>
          ))}
          {data?.versions.find((v) => v.name === name)?.diagnosis && (
            <>
              <h3>diagnosis.json — why this version exists</h3>
              <div className="code">
                <pre>{JSON.stringify(data.versions.find((v) => v.name === name)?.diagnosis, null, 1)}</pre>
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
