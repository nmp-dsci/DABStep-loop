import { useMemo, useState } from 'react';
import { type Task, useGet } from '../lib/api';

export function Tasks() {
  const [split, setSplit] = useState<'dev' | 'all'>('dev');
  const [level, setLevel] = useState<'' | 'easy' | 'hard'>('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const { data } = useGet<Task[]>(`/api/tasks?split=${split}`);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((t) => (!level || t.level === level) && (!needle || t.question.toLowerCase().includes(needle)));
  }, [data, level, q]);
  const per = 50;
  const shown = rows.slice(page * per, page * per + per);

  return (
    <>
      <p className="label">Benchmark tasks</p>
      <h1>
        Ten tasks carry an answer; <em>450</em> carry only a question
      </h1>
      <p className="lead">
        The dev split is the only gold this project uses. The 450 leaderboard tasks are permutations of 95 core questions
        over other merchants, months and fee rules; they are shown here for reading, never scored in this build.
      </p>
      <div className="row">
        <select value={split} onChange={(e) => { setSplit(e.target.value as 'dev' | 'all'); setPage(0); }} aria-label="split" style={{ maxWidth: 220 }}>
          <option value="dev">dev · 10 with gold</option>
          <option value="all">all · 450 without gold</option>
        </select>
        <select value={level} onChange={(e) => { setLevel(e.target.value as '' | 'easy' | 'hard'); setPage(0); }} aria-label="level" style={{ maxWidth: 160 }}>
          <option value="">easy + hard</option>
          <option value="easy">easy</option>
          <option value="hard">hard</option>
        </select>
        <input type="text" placeholder="search questions" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} style={{ maxWidth: 360 }} />
        <span className="muted small">{rows.length} tasks</span>
      </div>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>id</th>
              <th>level</th>
              <th>question</th>
              <th>guidelines</th>
              {split === 'dev' && <th>gold</th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => (
              <tr key={t.task_id}>
                <td className="num">{t.task_id}</td>
                <td>{t.level}</td>
                <td className="q wrap">{t.question}</td>
                <td className="wrap small muted">{t.guidelines}</td>
                {split === 'dev' && <td className="mono wrap">{t.answer}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > per && (
        <div className="row">
          <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>previous</button>
          <span className="muted small">page {page + 1} of {Math.ceil(rows.length / per)}</span>
          <button className="btn" disabled={(page + 1) * per >= rows.length} onClick={() => setPage(page + 1)}>next</button>
        </div>
      )}
    </>
  );
}
