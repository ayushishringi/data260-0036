# AI Use — DATA-260 HW2

## 1. What I used an AI assistant for and what I did myself

I used ChatGPT/Codex to help understand the HW2 requirements, plan the FastAPI and LangGraph structure, draft code examples, and organize the required experiment and report files.

I independently created the files in my repository, installed the Python packages, ran the FastAPI server, tested the frontend, executed the add/update/delete/search operations, ran the LangGraph workflow, completed the 30-run schema experiment, completed the turn-ceiling comparison, and completed the adversarial experiment.

## 2. One AI-produced output that was wrong or unsuitable

The first version of the LangGraph turn-ceiling logic stopped immediately after the first invalid Planner output when the ceiling was set to 2. This meant the Planner did not receive an opportunity to retry.

## 3. How I detected and verified the problem

I detected the problem during the adversarial experiment. The output showed:

- `planner_attempts: 1`
- `Hit turn ceiling`

The validation errors showed that the Planner output had four tags and a summary longer than 25 words. This confirmed that Pydantic detected the invalid output, but the graph stopped before allowing the required retry.

## 4. What I changed and why it works now

I changed the turn-ceiling comparisons so that the Planner can retry while the turn count is within the configured ceiling. The graph now allows a second Planner attempt before stopping.

I reran the adversarial experiment after the change. All five runs attempted the Planner twice, reached the turn ceiling safely, and did not hang:

- Runs: 5
- Planner attempts per run: 2
- Runs reaching the ceiling: 5
- Completion rate: 0%

This confirms that validation errors are fed back into the graph and that the loop terminates safely.