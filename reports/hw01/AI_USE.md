# AI use — HW1

1. **What an AI assistant was used for vs. what I did.** Cursor (Grok) drafted the HTML/JS form, Docker files, Ollama adapter, Planner/Reviewer/Finalizer script, and report scaffolding from `260_HW_1.pdf`. I supplied SID4 `0036`, confirmed the domain mapping, and ran (or will run) Ollama, the browser form, Docker/ECS screenshots, and the 40-run experiment on this machine.

2. **One AI-produced output that was wrong/unsuitable, or independently verified.** The first model-client sketch assumed LangChain `ChatOllama` on Python 3.13/3.9. This Mac only has system Python 3.9.6, and the handout warns 3.13 + LangChain/numpy. I independently verified `python3 --version` and `ollama list` (`qwen3:4b` present, no Docker/AWS CLI).

3. **How the problem was detected / verified.** `which docker` and `aws` failed; `python3` reported 3.9.6; a LangChain install would have been both unnecessary and fragile. A one-shot `agents_demo.py` run against Ollama is the check that tags/summary JSON actually parse.

4. **What changed and why it works now.** All model calls go through `src/model_client.py` using Ollama’s HTTP `/api/chat` (stdlib `urllib`), with `format=json` / JSON schema and `think: false` so Qwen3 does not wrap answers in reasoning text. No LangChain dependency, so Python 3.9 can still run the homework while remaining compatible with 3.11/3.12.
