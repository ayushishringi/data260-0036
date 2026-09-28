# AI Use Disclosure

## 1. What I Used an AI Assistant For

I used an AI assistant for:

- Understanding the HW4 requirements and organizing the implementation steps.
- Learning how to connect the React frontend to the FastAPI backend.
- Debugging Vite, React Router, CORS, cookies, and session issues.
- Understanding MySQL persistence and server-side authentication.
- Learning how SQLAlchemy relationships can create the N+1 query problem.
- Planning the naive and optimized database benchmark.
- Learning how to add a database index and interpret EXPLAIN output.
- Organizing the RAG corpus, documents, and evaluation questions.
- Learning how chunking and FAISS vector retrieval work.
- Reviewing benchmark results, RAG metrics, and verification outputs.
- Receiving step-by-step explanations of the code and debugging process.

## 2. What I Did Myself

I personally:

- Created and edited the project files.
- Installed the required Python and JavaScript dependencies.
- Created the MySQL database and tables.
- Implemented and tested authentication and CRUD operations.
- Added and verified the package-name database index.
- Ran the N+1 benchmark.
- Prepared the RAG documents and evaluation questions.
- Ran the chunked FAISS retrieval experiment.
- Ran the local FLAN-T5 generation experiment.
- Checked generated answers and refusal behavior.
- Captured screenshots for the report.
- Ran the verification script and frontend build.
- Committed and pushed the final repository changes.

## 3. AI-Generated Output That Required Revision

The first RAG implementation embedded entire documents and used manual cosine similarity. It did not satisfy the required chunk-level retrieval design.

The initial RAG evaluation also used only answerable questions and did not test ambiguity, unsupported questions, or unrelated questions.

I revised the implementation to use:

- 500-token chunks
- 50-token overlap
- FAISS vector retrieval
- Retrieved document and chunk identifiers
- Similarity scores
- A local `google/flan-t5-base` generation model
- Ambiguous, unsupported, and unrelated evaluation questions
- Refusal, faithfulness, accuracy, and format-compliance metrics

## 4. How I Verified the Final Result

I verified the final implementation by:

- Running the FastAPI health check.
- Testing registration and login.
- Testing protected API requests with HTTP-only session cookies.
- Testing GET, POST, PUT, and DELETE report operations.
- Confirming the MySQL tables and stored records.
- Running the N+1 benchmark with 5,000 reports and 200 advisories.
- Running the RAG experiment with 21 chunks and 72 evaluation rows.
- Running the HW4 verification script successfully.
- Running the React frontend production build successfully.

The local language model occasionally produced incomplete answers. Therefore, I added a grounded fallback that extracts supported package, vulnerability, and fixed-version fields from the retrieved advisory documents. The final system still includes an actual local language-model generation step, while the fallback prevents unsupported or incomplete answers from being reported as final answers.