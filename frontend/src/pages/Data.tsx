import { useState } from 'react';
import { useGet } from '../lib/api';

type Files = { dir: string; sampled: boolean; files: { name: string; bytes: number; structure: Record<string, unknown> }[] };
type FileBody =
  | { name: string; kind: 'csv'; columns: string[]; rows: string[][]; total_rows: number }
  | { name: string; kind: 'json'; records: Record<string, unknown>[]; total_records: number }
  | { name: string; kind: 'text'; text: string };

export function Data() {
  const { data } = useGet<Files>('/api/data/files');
  const [sel, setSel] = useState<string>('payments.csv');
  const { data: body, loading } = useGet<FileBody>(sel ? `/api/data/files/${sel}` : null);

  return (
    <>
      <p className="label">Benchmark context</p>
      <h1>
        Seven files, one <em>manual</em> — every question is answered from these
      </h1>
      <p className="lead">
        A payments table of 138,236 transactions, a thousand fee rules, thirty merchants, and a manual that defines how the
        rules apply. The agent sees the file structures below in every prompt and reads the rest with Python.
      </p>
      {data?.sampled && (
        <p className="small">
          <span className="v-warn">partial:</span> this deployment carries the committed sample — the first 500 rows of{' '}
          <code>payments.csv</code> and every other file in full. Counts on this page come from the sample.
        </p>
      )}

      <h2>1 · Files — pick one to see its rows</h2>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>file</th>
              <th className="num">bytes</th>
              <th>shape</th>
              <th>columns / keys</th>
            </tr>
          </thead>
          <tbody>
            {data?.files.map((f) => {
              const s = f.structure as { file_type?: string; keys?: string[]; sample_row?: Record<string, string>; n_records?: number };
              const cols = s.keys ?? (s.sample_row ? Object.keys(s.sample_row) : []);
              return (
                <tr key={f.name} className={`click ${sel === f.name ? 'pro' : ''}`} onClick={() => setSel(f.name)}>
                  <td className="sub">
                    <button className="linkbtn" onClick={() => setSel(f.name)}>
                      {f.name}
                    </button>
                    <span className="path">{data.dir}/{f.name}</span>
                  </td>
                  <td className="num">{f.bytes.toLocaleString()}</td>
                  <td>{s.file_type === 'json' ? `array · ${s.n_records ?? '?'} records` : s.file_type ?? '—'}</td>
                  <td className="wrap mono small">{cols.filter((c) => c).join(', ') || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h2>2 · {sel} — the first rows, as the agent reads them</h2>
      {loading && <p className="muted">loading…</p>}
      {body?.kind === 'csv' && (
        <>
          <p className="small muted">
            {body.rows.length} of {body.total_rows.toLocaleString()} rows shown.
          </p>
          <div className="tw">
            <table>
              <thead>
                <tr>
                  {body.columns.map((c, i) => (
                    <th key={i}>{c || '(index)'}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.rows.map((r, i) => (
                  <tr key={i}>
                    {r.map((v, j) => (
                      <td key={j} className={/^-?\d+(\.\d+)?$/.test(v) ? 'num' : ''}>
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {body?.kind === 'json' && (
        <>
          <p className="small muted">
            {body.records.length} of {body.total_records.toLocaleString()} records shown. <code>null</code> or <code>[]</code> in a
            fee rule field means the rule applies to every value of that field.
          </p>
          <div className="code">
            <pre>{JSON.stringify(body.records, null, 1)}</pre>
          </div>
        </>
      )}
      {body?.kind === 'text' && (
        <div className="code">
          <pre>{body.text}</pre>
        </div>
      )}
    </>
  );
}
