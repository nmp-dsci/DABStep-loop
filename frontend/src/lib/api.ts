import { useEffect, useState } from 'react';

export type Health = { status: string; mode: 'demo' | 'live'; champion: string | null; champion_fingerprint: string | null; code_sha: string };
export type Task = { task_id: string; question: string; guidelines: string; level: string; answer: string; has_gold: boolean; split?: string };
export type Summary = { n: number; n_scored: number; passed: number; pass_rate: number | null; easy_passed: number; easy_n: number; hard_passed: number; hard_n: number; failed_ids: string[]; errored_ids: string[]; cost_usd: number; duration_ms: number };
export type RunMeta = { run_id: string; agent: string; fingerprint: string; model: string; split: string; n_tasks: number; workers: number; passes: number; dry_run: boolean; started_at: string; finished_at: string | null; code_sha: string; summary: Summary | null; mlflow_run_id: string | null; note: string };
export type TaskResult = { task_id: string; level: string; question: string; gold: string; agent_answer: string; correct: boolean | null; n_turns: number; duration_ms: number; cost_usd: number | null; input_tokens: number; output_tokens: number; error: string | null; terminal_reason: string | null };
export type Diagnosis = { task_id: string; symptom: string; root_cause: string; surface: string; change: string; verified_in_session: boolean; verification?: string };
export type LedgerEntry = { cycle: number; kind: string; champion: string; champion_run?: string; challenger: string | null; optimiser_model?: string; failed: string[]; diagnoses?: Diagnosis[]; prompt_diff_summary?: string; helper_diff_summary?: string; expected_to_fix?: string[]; risks?: string[]; optimiser?: { turns: number; duration_ms: number; cost_usd_est: number | null; error: string | null }; tokens?: Record<string, number>; outcome?: { verdict: string; reason?: string; passes?: string; fixed?: string[]; broken?: string[]; still_failed?: string[]; challenger_run?: string }; at?: string; summary?: string; notes?: string[]; groups?: unknown };
export type RegistryEntry = { agent: string; fingerprint: string; run_id: string; model: string; split: string; passed: number | null; n_scored: number | null; at: string };
export type Registry = { champion: RegistryEntry | null; challenger: RegistryEntry | null; history: (RegistryEntry & { event: string })[] };
export type AgentInfo = { name: string; fingerprint: string; config: Record<string, unknown>; has_helper: boolean; helper_functions: string[]; diagnosis: Record<string, unknown> | null; runs: string[] };
export type Event = { type: string; [k: string]: unknown };

export async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return (await r.json()) as T;
}

export function useGet<T>(url: string | null): { data: T | null; error: string | null; loading: boolean } {
  const [state, set] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: !!url });
  useEffect(() => {
    if (!url) return;
    let alive = true;
    set({ data: null, error: null, loading: true });
    get<T>(url)
      .then((d) => alive && set({ data: d, error: null, loading: false }))
      .catch((e: Error) => alive && set({ data: null, error: e.message, loading: false }));
    return () => {
      alive = false;
    };
  }, [url]);
  return state;
}

export function fmtPct(x: number | null | undefined): string {
  return x == null ? '—' : `${Math.round(x * 100)}%`;
}
export function fmtS(ms: number | null | undefined): string {
  return ms == null ? '—' : `${(ms / 1000).toFixed(0)}s`;
}
export function fmtK(n: number | null | undefined): string {
  if (n == null) return '—';
  return n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);
}
export function shortRun(id: string): string {
  return id.replace(/^\d{8}T\d{6}Z_/, '');
}
export function when(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toISOString().slice(0, 16).replace('T', ' ') + 'Z';
}
