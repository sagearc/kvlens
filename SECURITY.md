# Security Policy

## Reporting a vulnerability

Use GitHub's private advisory (**Security → Report a vulnerability**) rather than
a public issue.

## Data provenance (read before committing data)

kvlens replays LLM traces. Real traces (e.g. SWE-bench Pro / Codex) can carry
licensed content and third-party agent prompts. The committed demo data
(`web/run.json`, `web/kv_events.json`) is generated from a synthetic trace
(`examples/gen_demo_trace.py`) and contains none of that.

**Never commit artifacts captured from a real dataset.** A pre-commit hook
(`scripts/check_no_leak.py`) scans `web/*.json` for known markers and blocks such
commits — treat a failure as a real leak. Raw datasets are git-ignored.
