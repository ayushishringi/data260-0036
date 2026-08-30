# AI Use — HW1

1. **What AI assistants were used for versus what I did.**  
   I used ChatGPT/Codex to help draft and review the Ollama model adapter, Planner–Reviewer–Finalizer pipeline, verification scripts, and report structure. I reviewed the generated code, executed every command, tested the form, ran Docker and Ollama locally, completed the 40-run nondeterminism experiment, and collected the report evidence.

2. **AI-produced output that was wrong or unsuitable.**  
   The Qwen3 Reviewer sometimes incorrectly changed the valid version range `3.21-3.25` to forms such as `3.21-3:25`. Additionally, Ollama sometimes returned internal reasoning text even though the request specified `think: false`.

3. **How the problems were detected and verified.**  
   I detected the version-range error by comparing the Planner, Reviewer, and Finalizer console outputs. I detected the reasoning-text problem through a direct Ollama API test and unusually large output-token counts. I reran the agent pipeline and five-turn client after making corrections and verified the saved machine-readable results.

4. **What changed and why it works now.**  
   I added deterministic validation that preserves a valid Planner summary when it is already within the 25-word limit and accurately calculates the Reviewer’s `changed` value. I also updated `src/model_client.py` to remove reasoning text ending in `</think>` before returning model content. The project now runs in a Python `3.12.14` virtual environment, produces clean bullet-only responses, records per-turn and cumulative token counts, and passes `scripts/verify_hw01.py`.