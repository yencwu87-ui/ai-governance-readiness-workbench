# WB-053 — Ollama search + challenger hardening

The web-search path is now a reusable `ollama_search.search_web()` adapter and the knowledge resolver consumes it. The Challenger now uses the dedicated challenge model role, optional model-call telemetry, tolerant action canonicalisation, robust JSON extraction, and deterministic validation retries.

The retry does not turn unsupported output into a finding: the same evidence-pointer, requirement-pointer, claim-test and allowed-action gates run after every attempt. If the final attempt fails, nothing is recorded.

## Configuration

```bash
export OLLAMA_URL=http://localhost:11434
export OLLAMA_MODEL=llama3.1:8b
export WB_MODEL_CHALLENGE=llama3.1:8b
export WB_WEB_KNOWLEDGE=auto
export WB_WEB_MAX_RESULTS=5
export WB_CHALLENGE_RETRIES=2
export WB_LLM_OBSERVE=1
```
