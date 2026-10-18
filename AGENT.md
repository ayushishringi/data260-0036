# Durable Agent Instructions

## Project description

- This project implements DATA-260 homework APIs for open-source package vulnerability analysis.

## Technology stack

- Use Python 3.12, FastAPI, Pydantic, PyMongo, MongoDB, and the local Ollama model.

## Coding conventions

- Keep route handlers thin and place business logic in separate service modules.
- Validate external input with Pydantic and return clear HTTP errors.

## Testing approach

- Test successful behavior, validation failures, persistence, and deterministic file operations before committing.

## Prohibited actions

- Do not expose secrets, delete unrelated user data, or modify unrelated homework evidence.
