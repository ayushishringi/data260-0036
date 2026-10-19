# AI Use — HW6

**1. What I used an AI assistant for, and what I did myself.**
I used AI coding assistants to draft the FastAPI routes, the PyMongo collection
and validator setup, the memory-service functions, the file-memory commands and
the experiment and verification scripts, and later to review the report
against the assignment. I chose the domain mapping (vulnerability documents),
the planted facts and probe questions, and the pricing/cost method; I ran the
servers, Swagger UI requests, mongosh queries and experiments, checked the
outputs, and took the screenshots.

**2. One AI-produced output that was wrong.**
The first AI-written Part 3 runner (`scripts/run_hw6_memory_cost.py`) took
`--settings 4/12/30` and `--policy` only as *labels*. The server reads
`SHORT_TERM_N` and `MEMORY_POLICY` from its environment once at start-up, and
the API was running with neither variable set. So all four "settings" in my
first results table were really `SHORT_TERM_N=12, window`. The table's
6.3 % "savings" and identical 5.0 probe scores were noise. A second problem
was that the probes asked about DATA-260/MongoDB/FastAPI, which are also in
AGENT.md and MEMORY.md (both go into every system prompt), so the probes could
not detect memory loss. Separately, the first `/compact` implementation
truncated MEMORY.md to 40 lines, which silently dropped facts.

**3. How I detected it.**
In `chat_costs.jsonl` the N=4 run carried about 6,000 short-term-window tokens
per turn, the same as the N=30 run, which is impossible for a 4-message window.
`ps -E` on the uvicorn process showed no `SHORT_TERM_N` or `MEMORY_POLICY` in its
environment. The probes all scored 5.0 even when the planted fact was outside
every window, which pointed to the file memory answering them.

**4. What I changed and why it works now.**
The runner now starts a fresh uvicorn process per configuration with the
variables set, and every `/api/chat` response echoes the active config
(`usage.config`). The runner aborts if that config does not match the one
requested. The per-turn CSV shows the window size actually changing
(`short_term_message_count`). The probes now ask about facts planted at turns
2, 9, 17, 23 and 27 that appear nowhere in AGENT.md or MEMORY.md. Consolidation
now merges duplicates and records every superseded value under
"Resolved contradictions" instead of truncating, and unit tests cover this.
The invalid runs are kept under `reports/hw06/raw/superseded/` for transparency.
