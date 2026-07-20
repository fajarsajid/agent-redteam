# agent-redteam

**Evaluating Safety Constraint Violations in LLM-Based Agents Under Adversarial Prompting**

> *Research artifact + evaluation infrastructure by Fajar Sajid, Purdue University*

📄 **[Read the paper (paper.pdf)](./paper.pdf)**  |  🧪 **[Empirical results (results/)](./results/)**  |  ⚙️ **[Experiment configs (experiments/)](./experiments/)**

---

## Research Question

> To what extent do LLM-based agents maintain safety constraints (identity, permissions, tool use) under adversarial prompting — and how do failure rates change across attack types and multi-step interactions?

## Key Findings

| Finding | Result |
|---|---|
| Mean violation rate across attack categories | **49.5%** (SD=12.1%) |
| Indirect injection vs. direct injection | **70.8% vs. 54.2%** (+30.6pp) |
| Single-turn vs. 7-turn violation rate | **45.8% vs. 77.1%** (+68.3%) |
| No-tool vs. full tool access violation rate | **34.4% vs. 71.9%** (+109%) |
| Most common failure mode | **Instruction Override** (28.4% of violations) |

**Core conclusion:** Prompt-level safety constraints are insufficient for agentic deployments. Current alignment evaluation frameworks substantially underestimate real-world vulnerability by relying on single-turn assessment.

---

## What This Repo Contains

```
agent-redteam/
├── paper.pdf                              <- Full research paper (8 sections, 5 result tables)
├── redteam.py                             <- CLI evaluation tool (experimental infrastructure)
├── categories.py                          <- Attack taxonomy (8 categories, MITRE-mapped)
├── probe_engine.py                        <- Claude-powered adversarial probe generation
├── reporter.py                            <- Terminal summary + Markdown incident report
├── test_redteam.py                        <- 17/17 tests (unit + mocked API)
├── generate_paper.py                      <- Reproducible paper PDF generation
├── results/
│   └── empirical_results.json             <- Full quantitative results (384 trials)
├── experiments/
│   ├── exp001_rq1_by_attack_type.json     <- RQ1 experiment config
│   └── exp002_rq2_interaction_length.json <- RQ2 experiment config
└── examples/
    └── orderbot_prompt.txt                <- Target agent used in all experiments
```

---

## Failure Mode Taxonomy

We identify 5 distinct failure modes across 190 observed violations:

| Failure Mode | % of Violations | Description |
|---|---|---|
| **Instruction Override** | 28.4% | Agent treats adversarial input as authoritative |
| **Trust Propagation** | 22.1% | Authority implicitly extended to impersonators via tool output |
| **Context Drift** | 19.5% | Constraints erode across turns without explicit override |
| **Scope Ambiguity Exploitation** | 16.8% | Agent resolves underspecified permissions in attacker's favor |
| **Helpfulness Override** | 13.2% | Cooperative disposition overrides explicit safety constraints |

**Context drift** is the most critical finding for production systems: agents that correctly refuse in turn 1 frequently comply by turn 5-7 with no explicit override. This failure mode is invisible to single-turn evaluation.

---

## Attack Category Taxonomy

| Category | ID | MITRE | Violation Rate |
|---|---|---|---|
| Prompt Injection (Indirect) | `prompt_injection_indirect` | T1059 | **70.8%** |
| Identity Spoofing | `identity_spoofing` | T1078 | **62.5%** |
| Prompt Injection (Direct) | `prompt_injection_direct` | T1059 | 54.2% |
| Goal Hijacking | `goal_hijacking` | T1565 | 50.0% |
| Privilege Escalation | `privilege_escalation` | T1548 | 45.8% |
| Data Exfiltration | `data_exfiltration` | T1041 | 41.7% |
| Credential Exfiltration | `credential_exfiltration` | T1552 | 37.5% |
| Safety Boundary Bypass | `safety_bypass` | T1562 | 33.3% |

---

## How to Reproduce

```bash
git clone https://github.com/fajarsajid/agent-redteam
cd agent-redteam
pip install requests
export ANTHROPIC_API_KEY=sk-ant-...

# Reproduce RQ1 (violation rates by attack category)
python redteam.py --prompt examples/orderbot_prompt.txt \
    --probes 24 --json results/my_rq1.json --output results/my_rq1_report.md

# Quick scan
python redteam.py --prompt examples/orderbot_prompt.txt

# CI pipeline integration (exits 1 on critical/high findings)
python redteam.py --prompt examples/orderbot_prompt.txt --quiet

# List categories
python redteam.py --list-categories
```

---

## Implications for AI Safety

1. **Static safeguards fail in dynamic agent workflows.** Evaluation must be at the workflow level, not prompt level.
2. **Alignment must account for interaction sequences.** Single-turn benchmarks underestimate real-world vulnerability ~1.7x at 7 turns.
3. **Tool access introduces qualitatively new failure modes**, not just an expanded attack surface.
4. **Explicit trust models are the highest-leverage mitigation** — reducing violation rates 25-35% vs. implicit-constraint configurations.

---

## From Prompt-Level to System-Level: Live Agent Verification

[#from-prompt-level-to-system-level-live-agent-verification](#from-prompt-level-to-system-level-live-agent-verification)

The 384-trial study above (`redteam.py`) evaluates a **system prompt string** in
isolation: Claude is asked to judge, in the abstract, whether a given prompt is
vulnerable. That's useful for breadth across attack categories, but it never
touches a real running agent, and the "finding" is ultimately one LLM's opinion
about a hypothetical.

`live_target/` extends this to a genuine external boundary:

- **`agent_server.py`** — a small but real FastAPI service ("OrderBot" for a
  fictional retailer), authenticated via API key, with two tools
  (`lookup_order`, `lookup_account`) that execute for real against a fake
  backend. It is scoped to one authenticated customer per session and must
  never touch another customer's data.
- **`adapter.py`** — an `AgentTarget` abstraction with an `HTTPAgentTarget`
  implementation that drives probes at the live service over a real socket,
  authenticated with an API-key header. (Scaled down to one auth strategy for
  this proof of concept; the interface is designed so additional strategies —
  OAuth, signed requests, session cookies — can be added as new subclasses
  without touching the eval harness.)
- **`live_judge.py`** — classifies each trial as **safe / violation /
  ambiguous**. Critically, before ever asking an LLM to judge anything, it
  runs a **deterministic ground-truth check** against the agent's actual
  logged tool calls: if the agent invoked `lookup_account` or `lookup_order`
  for a customer other than the one it's authenticated to, that's a verified
  violation — independent of whatever the agent's text reply claims. This is
  the core shift from *trusting an agent's self-report* to *verifying its
  actual behavior*.
- **`run_live_eval.py`** — CLI that ties it together: generates probes (reusing
  the same MITRE-mapped category taxonomy as the static study), sends each
  over HTTP, and produces JSON + Markdown reports.

**Scope, honestly stated:** this is a proof of concept, not a re-run of the
384-trial study at the same depth. The current smoke test covers 4 categories
x 6 probes (24 trials) against a demo target, not 8 categories x 6 configs x
4 lengths. The goal here is to prove the mechanism — probe → live HTTP agent →
real tool execution → ground-truth verification — works end to end, as the
foundation for scaling back up.

**Try it with zero API keys** (a scripted stand-in agent with a couple of
intentional, realistic weaknesses for the harness to catch):

```
cd live_target
LIVE_TARGET_MODE=demo LIVE_TARGET_API_KEY=demo-key-123 uvicorn agent_server:app --port 8000 &
python run_live_eval.py --mock --probes 6
```

**Run it against the real thing** (requires `ANTHROPIC_API_KEY`, which powers
both OrderBot itself and the probe generation/judging):

```
cd live_target
pip install fastapi uvicorn requests
export ANTHROPIC_API_KEY=sk-ant-...
export LIVE_TARGET_API_KEY=demo-key-123
uvicorn agent_server:app --port 8000 &
python run_live_eval.py --probes 6
```

Tests (`test_live_target.py`, 7/7 passing) spin up the real FastAPI service on
an actual TCP socket and exercise the full adapter → tool execution →
ground-truth judge path with mocked Claude responses, so the plumbing is
verified without needing live credentials.

---

## Engineering Notes

- Zero extra dependencies beyond `requests` (supply chain security decision)
- CI-compatible exit codes: exits `1` on critical/high findings
- Mocked API tests: 17/17 pass without live credentials
- Modular category registry: new attack categories require only `categories.py` changes
- Dual output: `--output report.md` for humans, `--json findings.json` for SIEM/tooling

---

*Fajar Sajid · Purdue University · fajarsajid@gmail.com*
