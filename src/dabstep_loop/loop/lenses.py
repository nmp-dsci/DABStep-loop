"""Lenses 2 and 3 over the 450, and how far they agree with lens 1.

Lens 1 (`families.py`) is a rule. It is the id every card carries, and a rule
can be wrong in ways it cannot see. So two other views of the same 450
questions are computed once and committed next to it:

- lens 2: a local sentence-embedding model and k-means, k chosen by silhouette
  over 8–16 (no API call; `uv sync --extra lenses`);
- lens 3: one Sonnet pass over the 450. An agent first writes a one-paragraph
  summary of each embedding cluster from its questions; Sonnet then reads every
  question with those summaries and returns the cluster or clusters it fits,
  each with a confidence, so a question may belong to two.

The output is `loop/families/lenses.json`: per task the three assignments, an
adjusted Rand index and confusion matrix between every pair of lenses, and a
boundary flag where the lenses disagree or lens 3 is split. The sampler draws
boundary tasks first: they are where the method is likeliest to flip.

Nothing here reads a gold answer; a summary describes questions, never answers.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from math import comb
from typing import Any

from dabstep_loop.loop.families import FAMILIES_DIR, assign

LENSES_PATH = FAMILIES_DIR / "lenses.json"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SPLIT_THRESHOLD = 0.3  # a second lens-3 membership at or above this makes the task a boundary case


# --------------------------------------------------------------------------
# agreement, pure python so it is testable without the optional dependencies
# --------------------------------------------------------------------------
def adjusted_rand_index(a: list[str], b: list[str]) -> float:
    """Hubert & Arabie ARI between two labelings of the same items; 1 = identical partitions."""
    assert len(a) == len(b)
    n = len(a)
    if n < 2:
        return 1.0
    table: dict[tuple[str, str], int] = Counter(zip(a, b, strict=True))
    rows: dict[str, int] = Counter(a)
    cols: dict[str, int] = Counter(b)
    sum_cells = sum(comb(v, 2) for v in table.values())
    sum_rows = sum(comb(v, 2) for v in rows.values())
    sum_cols = sum(comb(v, 2) for v in cols.values())
    total = comb(n, 2)
    expected = sum_rows * sum_cols / total
    max_index = (sum_rows + sum_cols) / 2
    if max_index == expected:
        return 1.0
    return float((sum_cells - expected) / (max_index - expected))


def confusion(a: list[str], b: list[str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for x, y in zip(a, b, strict=True):
        out[x][y] += 1
    return {k: dict(v) for k, v in out.items()}


def majority_map(clusters: list[str], families: list[str]) -> dict[str, str]:
    """cluster → the lens-1 family most of its members carry."""
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for c, f in zip(clusters, families, strict=True):
        votes[c][f] += 1
    return {c: v.most_common(1)[0][0] for c, v in votes.items()}


def boundary_flags(
    l1: dict[str, str],
    l2: dict[str, str],
    l3: dict[str, list[dict[str, Any]]],
    cluster_to_family: dict[str, str],
) -> dict[str, list[str]]:
    """task → the reasons it is a boundary case (empty list = every lens agrees)."""
    out: dict[str, list[str]] = {}
    for tid, fam in l1.items():
        reasons: list[str] = []
        c2 = l2.get(tid)
        if c2 is not None and cluster_to_family.get(c2) != fam:
            reasons.append(f"lens 2 cluster {c2} is mostly {cluster_to_family.get(c2)}")
        m = sorted(l3.get(tid, []), key=lambda x: -float(x.get("confidence", 0)))
        if m:
            top = str(m[0]["cluster"])
            if cluster_to_family.get(top) != fam:
                reasons.append(f"lens 3 top cluster {top} is mostly {cluster_to_family.get(top)}")
            if len(m) > 1 and float(m[1].get("confidence", 0)) >= SPLIT_THRESHOLD:
                reasons.append(
                    f"lens 3 split: {top} {float(m[0].get('confidence', 0)):.2f} / "
                    f"{m[1]['cluster']} {float(m[1].get('confidence', 0)):.2f}"
                )
        out[tid] = reasons
    return out


# --------------------------------------------------------------------------
# lens 2: local embeddings + k-means
# --------------------------------------------------------------------------
def embed_and_cluster(
    questions: dict[str, str], k: int = 12, k_range: range = range(8, 17), seed: int = 0
) -> tuple[dict[str, str], dict[str, Any]]:
    """task → cluster id at a fixed k, with the silhouette curve over `k_range` recorded.

    k is fixed at the family count rather than chosen by silhouette: on these 450 the
    silhouette rises monotonically with k (0.23 at 8, 0.35 at 28) because the
    questions are permutations of 106 templates and the tightest clusters are the
    templates themselves. A fixed k keeps the confusion against the 12 families
    readable; the curve is kept so the choice can be argued with. Needs
    `uv sync --extra lenses`."""
    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.cluster import KMeans  # type: ignore[import-untyped]
        from sklearn.metrics import silhouette_score  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover - environment
        raise SystemExit("lens 2 needs the optional group: uv sync --extra lenses") from e

    ids = list(questions)
    model = SentenceTransformer(EMBEDDING_MODEL)
    x = model.encode([questions[i] for i in ids], normalize_embeddings=True)
    scores: dict[int, float] = {}
    for kk in sorted(set(k_range) | {k}):
        km = KMeans(n_clusters=kk, n_init=10, random_state=seed).fit(x)
        scores[kk] = round(float(silhouette_score(x, km.labels_)), 4)
    chosen = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(x)
    labels = {tid: f"C{int(lbl):02d}" for tid, lbl in zip(ids, chosen.labels_, strict=True)}
    return labels, {"model": EMBEDDING_MODEL, "k": k, "silhouette": scores, "seed": seed}


# --------------------------------------------------------------------------
# lens 3: cluster summaries, then one Sonnet membership pass
# --------------------------------------------------------------------------
def _cluster_sheet(cluster: str, members_: list[tuple[str, str]]) -> str:
    tpl_counts = Counter(t for _, t in members_)
    lines = [f"- ({n}×) {t}" for t, n in tpl_counts.most_common(12)]
    return f"## {cluster} · {len(members_)} questions, {len(tpl_counts)} templates\n" + "\n".join(
        lines
    )


SUMMARY_PROMPT = """You are describing clusters of benchmark questions about a payments dataset (transactions,
merchants, a fee-rule table, a manual). Below, each cluster is listed with its question templates
(merchant names, months, ids and numbers are blanked as <merchant>, <month>, <n> …) and how many
questions share each template.

Write one paragraph per cluster, 40–80 words, that says what these questions ask for and what
computation they need. Describe questions only; never guess or state an answer.

{sheets}

Reply with exactly one fenced ```json block: {{"summaries": {{"C00": "…", "C01": "…", …}}}}"""

MEMBERSHIP_PROMPT = """Below are summaries of {k} clusters of benchmark questions, then a batch of questions.
For every question, say which cluster or clusters it fits. Give each membership a confidence in
(0, 1]; list a second cluster only when the question genuinely fits both. Judge by what the
question asks for and the computation it needs, not by shared words. Never answer a question.

# Cluster summaries
{summaries}

# Questions
{questions}

Reply with exactly one fenced ```json block:
{{"memberships": {{"<task_id>": [{{"cluster": "Cnn", "confidence": 0.9}}, …], …}}}}
Every task_id in the batch must appear."""


def _parse_json_block(text: str) -> dict[str, Any]:
    m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        raise ValueError("no json block in the model's reply")
    return dict(json.loads(m[-1]))


async def _ask(prompt: str, model: str) -> tuple[str, dict[str, int]]:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )

    from dabstep_loop.agent.llm import EFFORT, resolve_model, subscription_env
    from dabstep_loop.config import ROOT

    options = ClaudeAgentOptions(
        model=resolve_model(model),
        effort=EFFORT,
        tools=[],
        allowed_tools=[],
        permission_mode="bypassPermissions",
        max_turns=1,
        cwd=str(ROOT),
        env=subscription_env(),
        setting_sources=[],
    )
    text = ""
    tokens = {"in": 0, "out": 0}
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        text = b.text
            elif isinstance(msg, ResultMessage):
                u = msg.usage or {}
                tokens["in"] += (
                    int(u.get("input_tokens", 0))
                    + int(u.get("cache_read_input_tokens", 0))
                    + int(u.get("cache_creation_input_tokens", 0))
                )
                tokens["out"] += int(u.get("output_tokens", 0))
                if msg.result and not text:
                    text = msg.result
    return text, tokens


async def summarise_clusters(
    l2: dict[str, str], tasks: dict[str, dict[str, Any]], model: str
) -> tuple[dict[str, str], dict[str, int]]:
    by: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for tid, c in l2.items():
        by[c].append((tid, str(tasks[tid]["template"])))
    sheets = "\n\n".join(_cluster_sheet(c, m) for c, m in sorted(by.items()))
    text, tokens = await _ask(SUMMARY_PROMPT.format(sheets=sheets), model)
    return {str(k): str(v) for k, v in _parse_json_block(text)["summaries"].items()}, tokens


async def membership_pass(
    summaries: dict[str, str],
    tasks: dict[str, dict[str, Any]],
    model: str,
    batch: int = 30,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    ids = sorted(tasks, key=int)
    summ = "\n".join(f"- {c}: {s}" for c, s in sorted(summaries.items()))
    out: dict[str, list[dict[str, Any]]] = {}
    total = {"in": 0, "out": 0}
    for i in range(0, len(ids), batch):
        chunk = ids[i : i + batch]
        qs = "\n".join(f"- {tid}: {tasks[tid]['question']}" for tid in chunk)
        text, tokens = await _ask(
            MEMBERSHIP_PROMPT.format(k=len(summaries), summaries=summ, questions=qs), model
        )
        total["in"] += tokens["in"]
        total["out"] += tokens["out"]
        got = _parse_json_block(text)["memberships"]
        for tid in chunk:
            m = got.get(tid) or got.get(str(tid)) or []
            out[tid] = [
                {"cluster": str(x["cluster"]), "confidence": float(x.get("confidence", 0))}
                for x in m
                if str(x.get("cluster", "")) in summaries
            ]
    return out, total


# --------------------------------------------------------------------------
# the whole thing
# --------------------------------------------------------------------------
def assemble(
    tasks: dict[str, dict[str, Any]],
    l2: dict[str, str],
    l2_meta: dict[str, Any],
    summaries: dict[str, str],
    l3: dict[str, list[dict[str, Any]]],
    model: str,
    tokens: dict[str, int],
) -> dict[str, Any]:
    ids = sorted(tasks, key=int)
    l1 = {tid: str(tasks[tid]["family"]) for tid in ids}
    l3_top = {
        tid: (
            str(sorted(l3.get(tid, []), key=lambda x: -x["confidence"])[0]["cluster"])
            if l3.get(tid)
            else "none"
        )
        for tid in ids
    }
    c2f = majority_map([l2[t] for t in ids], [l1[t] for t in ids])
    c3f = majority_map([l3_top[t] for t in ids], [l1[t] for t in ids])
    # lens 3 clusters are the lens 2 clusters by construction, so one map serves both;
    # keep lens 3's own majority for the confusion matrix and use lens 2's for flags.
    flags = boundary_flags(l1, l2, l3, c2f)
    a1, a2, a3 = [l1[t] for t in ids], [l2[t] for t in ids], [l3_top[t] for t in ids]
    return {
        "embedding": l2_meta,
        "membership_model": model,
        "tokens": tokens,
        "summaries": summaries,
        "cluster_to_family": {"lens2": c2f, "lens3": c3f},
        "agreement": {
            "ari": {
                "l1_l2": round(adjusted_rand_index(a1, a2), 4),
                "l1_l3": round(adjusted_rand_index(a1, a3), 4),
                "l2_l3": round(adjusted_rand_index(a2, a3), 4),
            },
            "confusion": {"l1_l2": confusion(a1, a2), "l1_l3": confusion(a1, a3)},
            "boundary_count": sum(1 for r in flags.values() if r),
            "split_count": sum(1 for r in flags.values() if any("split" in x for x in r)),
        },
        "tasks": {
            tid: {
                "family": l1[tid],
                "level": tasks[tid]["level"],
                "lens2": l2[tid],
                "lens3": l3.get(tid, []),
                "boundary": flags[tid],
            }
            for tid in ids
        },
    }


async def build_lenses(model: str = "sonnet", seed: int = 0, k: int = 12) -> dict[str, Any]:
    from dabstep_loop.agent.llm import require_live

    require_live()
    tasks = assign("all")
    l2, l2_meta = embed_and_cluster(
        {tid: str(t["question"]) for tid, t in tasks.items()}, k=k, seed=seed
    )
    summaries, t1 = await summarise_clusters(l2, tasks, model)
    l3, t2 = await membership_pass(summaries, tasks, model)
    tokens = {"in": t1["in"] + t2["in"], "out": t1["out"] + t2["out"]}
    doc = assemble(tasks, l2, l2_meta, summaries, l3, model, tokens)
    FAMILIES_DIR.mkdir(parents=True, exist_ok=True)
    LENSES_PATH.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def read_lenses() -> dict[str, Any] | None:
    if not LENSES_PATH.exists():
        return None
    return dict(json.loads(LENSES_PATH.read_text(encoding="utf-8")))


def boundary_task_ids() -> set[str]:
    doc = read_lenses()
    if not doc:
        return set()
    return {tid for tid, t in doc["tasks"].items() if t.get("boundary")}
