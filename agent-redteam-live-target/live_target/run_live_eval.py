#!/usr/bin/env python3
"""
run_live_eval.py — Probes a LIVE agent (agent_server.py) over real HTTP,
using the adapter layer, and verifies outcomes against ground-truth tool
call logs rather than the agent's self-reported text.

This is the live-target counterpart to redteam.py: same attack-category
taxonomy, same MITRE mapping, same Claude-powered probe generation — but
now aimed at a genuine HTTP boundary with real tool execution, using the
three-outcome schema (safe / violation / ambiguous) instead of a single
LLM's opinion about a system prompt string.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export LIVE_TARGET_API_KEY=demo-key-123
    uvicorn agent_server:app --port 8000 &
    python run_live_eval.py --probes 6

    # Or, fully offline (no API key needed anywhere):
    LIVE_TARGET_MODE=demo uvicorn agent_server:app --port 8000 &
    python run_live_eval.py --probes 6 --mock
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # import categories.py from repo root
from categories import ATTACK_CATEGORIES

from adapter import HTTPAgentTarget
from claude_client import ClaudeClient
from live_judge import judge_outcome
from live_probe_engine import generate_probe

# Categories most relevant to a live tool-using agent's authorization boundary.
LIVE_RELEVANT_CATEGORIES = [
    "prompt_injection", "privilege_escalation", "identity_spoofing", "data_exfiltration",
]

AUTHENTICATED_EMAIL = "alice@acme-customer.com"  # the "victim" whose session is being probed


def parse_args():
    p = argparse.ArgumentParser(description="Probe a live agent target over HTTP.")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--target-api-key", default="demo-key-123",
                   help="API key the live agent server expects (LIVE_TARGET_API_KEY)")
    p.add_argument("--categories", nargs="+", default=LIVE_RELEVANT_CATEGORIES)
    p.add_argument("--probes", type=int, default=6, metavar="N",
                   help="Probes per category (default 6; e.g. 4 categories x 6 = 24 trials)")
    p.add_argument("--mock", action="store_true",
                   help="Run fully offline: static seed probes + rule-based judge only, "
                        "no ANTHROPIC_API_KEY needed on this side. Pair with a server "
                        "started as LIVE_TARGET_MODE=demo.")
    p.add_argument("--json", default="live_findings.json")
    p.add_argument("--md", default="live_report.md")
    return p.parse_args()


def main():
    args = parse_args()

    probe_client = None
    judge_client = None
    if not args.mock:
        # Real run: use Claude both to craft tailored probes and to judge
        # ambiguous cases. Requires ANTHROPIC_API_KEY in the environment.
        probe_client = ClaudeClient()
        judge_client = ClaudeClient()

    target = HTTPAgentTarget(base_url=args.base_url, api_key=args.target_api_key)

    invalid = [c for c in args.categories if c not in ATTACK_CATEGORIES]
    if invalid:
        print(f"[ERROR] Unknown categories: {invalid}. "
              f"Valid: {list(ATTACK_CATEGORIES.keys())}")
        sys.exit(1)

    findings = []
    print(f"Target:      {args.base_url}")
    print(f"Categories:  {args.categories}")
    print(f"Probes/cat:  {args.probes}  (total: {len(args.categories) * args.probes})")
    print(f"Mode:        {'MOCK (offline)' if args.mock else 'LIVE (Claude API)'}")
    print("-" * 60)

    for cat_id in args.categories:
        cat_meta = ATTACK_CATEGORIES[cat_id]
        for probe_num in range(1, args.probes + 1):
            probe_text = generate_probe(cat_id, cat_meta, probe_num, client=probe_client)
            session_id = str(uuid.uuid4())

            try:
                result = target.send(message=probe_text, session_id=session_id,
                                      customer_email=AUTHENTICATED_EMAIL)
            except Exception as e:
                findings.append({
                    "category_id": cat_id, "category_name": cat_meta["name"],
                    "mitre": cat_meta["mitre"], "probe_number": probe_num,
                    "probe": probe_text, "outcome": "ambiguous",
                    "method": "target_unreachable", "rationale": str(e),
                    "reply": None, "tool_calls": [],
                })
                print(f"[{cat_id}] probe {probe_num}: TARGET ERROR ({e})")
                continue

            verdict = judge_outcome(
                probe=probe_text, reply=result["reply"], tool_calls=result["tool_calls"],
                authorized_email=AUTHENTICATED_EMAIL, category_name=cat_meta["name"],
                client=judge_client,
            )

            finding = {
                "category_id": cat_id,
                "category_name": cat_meta["name"],
                "mitre": cat_meta["mitre"],
                "probe_number": probe_num,
                "probe": probe_text,
                "reply": result["reply"],
                "tool_calls": result["tool_calls"],
                **verdict,
            }
            findings.append(finding)
            print(f"[{cat_id}] probe {probe_num}: {verdict['outcome'].upper()} "
                  f"({verdict.get('method', '?')})")

    write_reports(findings, args)

    violations = [f for f in findings if f["outcome"] == "violation"]
    sys.exit(1 if violations else 0)


def write_reports(findings, args):
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_base_url": args.base_url,
        "mode": "mock" if args.mock else "live",
        "categories": args.categories,
        "probes_per_category": args.probes,
        "total_trials": len(findings),
    }
    Path(args.json).write_text(json.dumps({"meta": meta, "findings": findings}, indent=2))

    safe = sum(1 for f in findings if f["outcome"] == "safe")
    violation = sum(1 for f in findings if f["outcome"] == "violation")
    ambiguous = sum(1 for f in findings if f["outcome"] == "ambiguous")

    gt_violations = [f for f in findings
                     if f["outcome"] == "violation" and f.get("method") == "ground_truth_tool_log"]

    lines = [
        "# Live Agent Evaluation Report", "",
        f"**Target:** `{args.base_url}`  ",
        f"**Mode:** {meta['mode']}  ",
        f"**Total trials:** {len(findings)}", "",
        "## Summary", "",
        f"| Outcome | Count | Rate |",
        f"|---|---|---|",
        f"| Safe | {safe} | {safe/len(findings)*100:.1f}% |" if findings else "| Safe | 0 | - |",
        f"| Violation | {violation} | {violation/len(findings)*100:.1f}% |" if findings else "| Violation | 0 | - |",
        f"| Ambiguous | {ambiguous} | {ambiguous/len(findings)*100:.1f}% |" if findings else "| Ambiguous | 0 | - |",
        "",
        f"**Ground-truth-verified violations (confirmed via real tool-call log, "
        f"not just agent self-report):** {len(gt_violations)}",
        "",
        "## Violations", "",
    ]
    for f in findings:
        if f["outcome"] != "violation":
            continue
        lines += [
            f"### {f['category_name']} — probe #{f['probe_number']} ({f['mitre']})", "",
            f"- **Method:** {f.get('method')}",
            f"- **Probe:** {f['probe'][:200]}",
            f"- **Rationale:** {f.get('rationale')}",
            f"- **Tool calls made:** {json.dumps(f['tool_calls'])}",
            "",
        ]
    Path(args.md).write_text("\n".join(lines))
    print("-" * 60)
    print(f"Safe: {safe}  Violation: {violation}  Ambiguous: {ambiguous}")
    print(f"Ground-truth-verified violations: {len(gt_violations)}")
    print(f"Written: {args.json}, {args.md}")


if __name__ == "__main__":
    main()
