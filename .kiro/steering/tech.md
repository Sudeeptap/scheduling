## Technology Stack

### Frontend
- React with TypeScript and Vite.
- Build a responsive chatbot interface for natural-language conversations.
- Display conversation history, loading/error states, doctor options, alternative appointment slots, and booking confirmations.
- Keep API calls and UI components separated.
- Do not expose the OpenAI API key in the browser.

### Backend
- Python with FastAPI.
- Use the official OpenAI Python SDK and Responses API with function calling.
- Keep conversation handling, tool execution, business logic, and database access separate.

### Database and Testing
- SQLite for the MVP.
- pytest for backend tests.
- Use frontend tests where appropriate.
- Store secrets in environment variables; never commit API keys.
- Keep dependencies minimal and avoid unnecessary frameworks.

## Development Rules
- Read `docs/requirements.md` and all existing `.mmd` diagrams before implementation.
- Treat existing diagrams as the baseline design; flag conflicts rather than silently redesigning.
- Implement one task at a time.
- Skip unit tests and automated test setup for the initial MVP.
- Prioritize getting the frontend, backend, Responses API tool calling, and database working end to end.
- Verify the main conversation and booking scenarios manually.
- Keep changes minimal and maintainable; avoid unrelated refactoring and duplicate code.
- Do not regenerate existing documentation or diagrams unless requested.
- Report implementation status, manual verification performed, and known issues honestly.