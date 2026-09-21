# AI Use Disclosure

## 1. What I Used an AI Assistant For

I used an AI assistant for:

- Understanding the HW3 requirements and organizing the implementation steps.
- Planning the FastAPI authentication and session-management structure.
- Reviewing Python import, routing, and middleware errors.
- Learning how to implement the three LlamaIndex chunking techniques.
- Debugging the retrieval pipeline and organizing the raw output files.
- Reviewing the generated retrieval metrics and comparing the techniques.

## 2. What I Did Myself

I personally:

- Created and edited the files in VS Code.
- Created the `hw3` Git branch and tag.
- Installed the required packages in the local Python virtual environment.
- Downloaded and prepared the local vulnerability-advisory corpus.
- Ran the server, authentication tests, timeout tests, retrieval experiments, and verification commands.
- Checked the terminal outputs and committed and pushed the final repository state.

## 3. AI-Produced Output That Was Unsuitable

The first retrieval implementation used LlamaIndex's default query engine. This caused LlamaIndex to attempt to use an OpenAI model and produced an error because no `OPENAI_API_KEY` was configured.

The error was:

```text
ValueError: No API key found for OpenAI.