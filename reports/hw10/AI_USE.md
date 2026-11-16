# AI Use — HW10

1. What I used AI for. I used an LLM to help with the code.

2. One AI output that was wrong. The first version of `traced_request()` built its result as `{"trace_id": ..., "status": "ok", **result}`. The cache handler's result also has a `status` key (the Reviewer's `"approved"`), which overwrote `"ok"`. The end-to-end script only waits for the evaluator when `status == "ok"`, so it skipped the wait and asked the next question while the first answer was still being judged.

3. How I found it. The first run printed `status=approved` on the request line, followed by `evaluation span: None None ms` right after the answer, although the evaluator log showed it had only just received the final message. A real evaluation takes minutes, so an instant `None` meant the wait never happened.

4. What I changed. The request status is now set after the merge, and the Reviewer's verdict is kept separately as `review_status`. The partial run's spans, evaluations and cache entry were deleted and `make e2e-hw10` was rerun from scratch.
