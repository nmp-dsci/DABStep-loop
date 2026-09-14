"""`file_structures.json`: what the agent is told about the files before it looks.

Ported from the NVIDIA recipe (`generate_file_structures.py`): one sample row
per CSV, keys plus one record per JSON. It is the first thing in every prompt,
so an agent does not spend its first turns discovering column names.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from dabstep_loop.config import DATA_DIR, context_dir

OUTPUT = DATA_DIR / "file_structures.json"


def _scan_csv(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f), None)
    return {"file_type": "csv", "sample_row": row or {}}


def _scan_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list) and data:
        sample = data[0]
        return {
            "file_type": "json",
            "structure_type": "array",
            "n_records": len(data),
            "keys": list(sample.keys()) if isinstance(sample, dict) else [],
            "sample_record": sample if isinstance(sample, dict) else {},
        }
    if isinstance(data, dict):
        return {"file_type": "json", "structure_type": "object", "keys": list(data.keys())}
    return {"file_type": "json", "structure_type": "unknown"}


def generate(directory: Path | None = None, output: Path = OUTPUT) -> dict[str, Any]:
    directory = directory or context_dir()
    structures: dict[str, Any] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        try:
            if path.suffix == ".csv":
                structures[path.name] = _scan_csv(path)
            elif path.suffix == ".json":
                structures[path.name] = _scan_json(path)
            elif path.suffix == ".md":
                structures[path.name] = {"file_type": "markdown", "bytes": path.stat().st_size}
        except Exception as e:  # noqa: BLE001 - a broken file is reported, not fatal
            structures[path.name] = {"error": str(e)}
    output.write_text(json.dumps(structures, indent=2, default=str) + "\n", encoding="utf-8")
    return structures


def render(structures: dict[str, Any] | None = None) -> str:
    """The prompt text: one block per file, exactly as the NVIDIA prompt did it."""
    if structures is None:
        structures = (
            json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else generate()
        )
    lines: list[str] = []
    for name, s in structures.items():
        if "error" in s:
            lines.append(f"- {name}: (error extracting structure)")
        elif s.get("file_type") == "csv":
            lines.append(f"- {name} (CSV):")
            lines.append(f"    Sample row: {json.dumps(s.get('sample_row', {}), default=str)}")
        elif s.get("file_type") == "json":
            lines.append(
                f"- {name} (JSON, {s.get('structure_type')}, {s.get('n_records', '?')} records):"
            )
            lines.append(f"    Keys: {', '.join(s.get('keys', []))}")
            lines.append(
                f"    Sample record: {json.dumps(s.get('sample_record', {}), default=str)}"
            )
        else:
            lines.append(f"- {name} ({s.get('file_type')}): read it first")
    return "\n".join(lines)
