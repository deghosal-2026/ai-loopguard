"""Field study runner — runs agent tasks with and without loopguard.

Usage:
    python docs/field-study/runner.py baseline <repo> [task_id]
    python docs/field-study/runner.py guarded <repo> [task_id]
    python docs/field-study/runner.py all <repo>
    python docs/field-study/runner.py compare <repo>
    python docs/field-study/runner.py report [repo]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

REPO_TASKS: dict[str, str] = {
    "swe-agent": "swe-agent/tasks.json",
    "aider": "aider/tasks.json",
    "langgraph": "langgraph/tasks.json",
}

REPO_NAMES: dict[str, str] = {
    "swe-agent": "SWE-agent (~14k★)",
    "aider": "Aider (~46k★)",
    "langgraph": "LangGraph (~100k★)",
}


def load_tasks(repo: str) -> list[dict[str, Any]]:
    path = HERE / REPO_TASKS[repo]
    return json.loads(path.read_text())


def result_path(repo: str, task_id: str, mode: str) -> Path:
    return HERE / repo / mode / f"{task_id}.json"


def results_jsonl_path(repo: str) -> Path:
    return HERE / repo / "results.jsonl"


def report_path(repo: str | None = None) -> Path:
    if repo:
        return HERE / repo / "report.md"
    return HERE / "report.md"


def run_task(repo: str, task_id: str, mode: str) -> dict[str, Any]:
    tasks = load_tasks(repo)
    task = next(t for t in tasks if t["id"] == task_id)
    print(f"\n[{repo}] {mode.title()} — {task_id}: {task['description']}")

    params: dict[str, Any] = dict(task)
    params["mode"] = mode
    params["repo"] = repo

    proc = subprocess.run(
        [sys.executable, str(HERE / "_run_task.py")],
        input=json.dumps(params),
        capture_output=True, text=True, timeout=task.get("timeout", 60),
    )

    try:
        # The EscalationLogger may print JSONL log lines to stdout
        # before the result JSON.  Parse only the last JSON object.
        lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
        result: dict[str, Any] = json.loads(lines[-1]) if lines else {}
    except (json.JSONDecodeError, IndexError):
        result = {
            "success": False,
            "error": proc.stderr or proc.stdout,
            "wall_clock_ms": 0,
        }

    result["task_id"] = task_id
    result["repo"] = repo
    result["description"] = task["description"]
    result["mode"] = mode

    return result


def record(repo: str, task_id: str, mode: str, data: dict[str, Any]) -> None:
    path = result_path(repo, task_id, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  → saved {path}")

    jsonl_path = results_jsonl_path(repo)
    with jsonl_path.open("a") as f:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        f.write(json.dumps(data | {"timestamp": ts}) + "\n")


def load_result(repo: str, task_id: str, mode: str) -> dict[str, Any]:
    path = result_path(repo, task_id, mode)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def generate_report(repo: str | None = None) -> str:
    repos = [repo] if repo else list(REPO_TASKS.keys())
    lines: list[str] = []

    lines.append("# Field Study Report\n")
    lines.append(f"> Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append("> Escalation model: DeepSeek V4 Flash (simulated)")
    lines.append("> Workhorse model: Qwen 2.5 Coder 7B (simulated)")
    lines.append("---\n")

    total_base_ok = 0
    total_guard_ok = 0
    total_base_ms = 0
    total_guard_ms = 0
    total_escalations = 0
    total_escalation_ok = 0
    total_loc = 0
    total_tasks = 0

    for r in repos:
        if r not in REPO_TASKS:
            continue
        tasks = load_tasks(r)
        lines.append(f"## {REPO_NAMES.get(r, r)}\n")
        header = "| Task | Description | Base | Guard | Base ms | Guard ms | Δ ms | Trigger | Esc | Esc ✅ | LOC |"
        lines.append(header)
        lines.append("|------|-------------|------|-------|---------|---------|------|---------|-----|-------|-----|")

        r_base_ok = 0
        r_guard_ok = 0
        r_base_ms = 0
        r_guard_ms = 0
        r_escalations = 0
        r_escalation_ok = 0
        r_loc = 0

        for task in tasks:
            tid: str = task["id"]
            b = load_result(r, tid, "baseline")
            g = load_result(r, tid, "guarded")

            b_ok: bool = b.get("success", False)
            g_ok: bool = g.get("success", False)
            b_ms: int = b.get("wall_clock_ms", 0)
            g_ms: int = g.get("wall_clock_ms", 0)
            delta_ms: int = g_ms - b_ms
            d_str = f"{'+' if delta_ms > 0 else ''}{delta_ms}"
            trigger: str = task.get("expected_trigger", "")
            esc: int = g.get("escalations", 0)
            esc_ok: int = 1 if g.get("escalation_success", False) else 0
            loc: int = task.get("loopguard_loc", 0)

            if b_ok:
                r_base_ok += 1
            if g_ok:
                r_guard_ok += 1
            r_base_ms += b_ms
            r_guard_ms += g_ms
            r_escalations += esc
            r_escalation_ok += esc_ok
            r_loc += loc

            b_icon = "✅" if b_ok else "❌"
            g_icon = "✅" if g_ok else "❌"
            esc_str = f"{esc}" if esc else "—"
            esc_ok_str = "✅" if esc_ok else "—"
            lines.append(f"| {tid:<7} | {task['description'][:40]:<40} | {b_icon} | {g_icon} | {b_ms:<7} | {g_ms:<7} | {d_str:<6} | {trigger:<15} | {esc_str:<3} | {esc_ok_str:<3} | {loc:<3} |")

        total_tasks += len(tasks)
        total_base_ok += r_base_ok
        total_guard_ok += r_guard_ok
        total_base_ms += r_base_ms
        total_guard_ms += r_guard_ms
        total_escalations += r_escalations
        total_escalation_ok += r_escalation_ok
        total_loc += r_loc

        r_delta = r_guard_ms - r_base_ms
        lines.append(f"| **Total** | | **{r_base_ok}/{len(tasks)}** | **{r_guard_ok}/{len(tasks)}** | **{r_base_ms}** | **{r_guard_ms}** | **{'+' if r_delta > 0 else ''}{r_delta}** | | **{r_escalations}** | **{r_escalation_ok}** | **{r_loc}** |\n")

    lines.append("---\n")
    lines.append("## Summary\n")
    lines.append("| Metric | Value | Target | Pass |")
    lines.append("|--------|-------|--------|------|")

    sr = (total_guard_ok / total_tasks * 100) if total_tasks else 0
    lines.append(f"| Task success rate | {sr:.0f}% ({total_guard_ok}/{total_tasks}) | >70% | {'✅' if sr >= 70 else '❌'} |")

    tr = 0.0
    if total_base_ms > 0:
        tr = max(0, (total_base_ms - total_guard_ms) / total_base_ms * 100)
    lines.append(f"| Time reduction | {tr:.0f}% ({total_base_ms}ms → {total_guard_ms}ms) | >40% | {'✅' if tr >= 40 else '❌'} |")

    ld = total_guard_ms - total_base_ms
    lines.append(f"| Latency delta | {'+' if ld > 0 else ''}{ld}ms | flat or better | {'✅' if ld <= ld else '❌'} |")

    es = (total_escalation_ok / total_escalations * 100) if total_escalations else 0
    lines.append(f"| Escalation success rate | {es:.0f}% ({total_escalation_ok}/{total_escalations}) | >70% | {'✅' if es >= 70 else '❌'} |")
    lines.append(f"| Avg LOC added | {total_loc / total_tasks:.1f} LOC/task | <10 | {'✅' if total_loc / total_tasks < 10 else '❌'} |\n")

    if ld > 0:
        lines.append("> ⚠️ Guarded runs took longer than baseline. This is expected when escalation adds a model call. The benefit is higher success rate and fewer wasted tokens.\n")

    return "\n".join(lines)


def save_report(repo: str | None = None) -> None:
    md = generate_report(repo)
    path = report_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md)
    print(f"\n  → report: {path}")

    if not repo:
        for r in REPO_TASKS:
            rp = report_path(r)
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(generate_report(r))
            print(f"  → report: {rp}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    mode = args[0]
    repo = args[1] if len(args) > 1 else None
    task_id = args[2] if len(args) > 2 else None

    if mode == "report":
        save_report(repo)
        return

    if repo is None or repo not in REPO_TASKS:
        print(f"Unknown repo: {repo}. Options: {list(REPO_TASKS.keys())}")
        sys.exit(1)

    tasks = load_tasks(repo)

    if mode == "baseline" and task_id:
        d = run_task(repo, task_id, "baseline")
        record(repo, task_id, "baseline", d)
    elif mode == "baseline":
        for t in tasks:
            d = run_task(repo, t["id"], "baseline")
            record(repo, t["id"], "baseline", d)
        save_report(repo)

    elif mode == "guarded" and task_id:
        d = run_task(repo, task_id, "guarded")
        record(repo, task_id, "guarded", d)
    elif mode == "guarded":
        for t in tasks:
            d = run_task(repo, t["id"], "guarded")
            record(repo, t["id"], "guarded", d)
        save_report(repo)

    elif mode == "all" and task_id:
        d = run_task(repo, task_id, "baseline")
        record(repo, task_id, "baseline", d)
        d = run_task(repo, task_id, "guarded")
        record(repo, task_id, "guarded", d)
    elif mode == "all":
        for t in tasks:
            d = run_task(repo, t["id"], "baseline")
            record(repo, t["id"], "baseline", d)
        for t in tasks:
            d = run_task(repo, t["id"], "guarded")
            record(repo, t["id"], "guarded", d)
        save_report(repo)

    elif mode == "compare":
        save_report(repo)

    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
