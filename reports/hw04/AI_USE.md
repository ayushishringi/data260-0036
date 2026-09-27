# AI Use Disclosure

## 1. What I Used an AI Assistant For

I used an AI assistant for:

- Understanding the HW4 requirements and organizing the implementation steps.
- Learning how to connect the React frontend to the FastAPI backend.
- Debugging Vite, React Router, CORS, cookie, and session errors.
- Understanding how server-side authentication works with MySQL sessions.
- Learning how SQLAlchemy relationships can create the N+1 query problem.
- Planning the naive and optimized database benchmark.
- Reviewing the N+1 latency and query-count results.
- Organizing the five-document RAG corpus and six evaluation questions.
- Reviewing the RAG retrieval metrics and experiment outputs.
- Organizing the HW4 report files and run logs.

## 2. What I Did Myself

I personally:

- Created and edited the project files in VS Code.
- Created the `hw4` Git branch.
- Installed the required Python, MySQL, and frontend dependencies.
- Created the MySQL database and verified its tables.
- Created and tested the authentication and CRUD endpoints.
- Created and tested the React login, report creation, update, and delete pages.
- Ran the frontend build and backend commands locally.
- Seeded the N+1 benchmark data and checked the database counts.
- Ran the N+1 and RAG experiments.
- Checked the terminal outputs and committed the final repository changes.

## 3. AI-Produced Output That Was Unsuitable

The initial RAG plan assumed that a generative language model might be available.
However, this project did not have an OpenAI API key or a local text-generation
model configured. I therefore used a deterministic extractive RAG approach
based on the locally available embedding and retrieval dependencies.

The RAG results document this limitation: basic and engineered context produced
the same answer-overlap score because both used the same deterministic
extractive answer function.