# Anna Text Summarizer

A polished AI-powered text summarization app built on **Anna AI OS** using a Python Executa and Anna's reverse Sampling capability.

The app allows users to paste longer text and generate a concise summary through Anna's hosted LLM runtime — without directly integrating third-party model SDKs or exposing external API keys.

---

## Overview

Anna Text Summarizer demonstrates how an Anna App can connect a frontend interface to a Python Executa and use Anna's native LLM infrastructure.

The project started from the official Anna App scaffold and was extended into a complete AI summarization workflow with input validation, loading states, error handling, responsive UI, and real end-to-end LLM execution.

### Application Flow

```text
User Input
    ↓
Anna App UI
    ↓
anna.tools.invoke()
    ↓
Python Executa
    ↓
sampling/createMessage
    ↓
Anna LLM Runtime
    ↓
Generated Summary
    ↓
App UI
```

---

## Features

- AI-powered text summarization
- Multi-line text input
- Input validation
- Character counter
- Loading state during generation
- Duplicate submission prevention
- User-friendly error handling
- Copy-to-clipboard support
- Responsive interface
- Python Executa integration
- Anna Protocol v2 capability negotiation
- Reverse Sampling through `sampling/createMessage`
- Anna-hosted LLM execution
- No direct third-party LLM API integration
- No external AI API keys required
- Built-in `ping` smoke test for Executa verification

---

## Tech Stack

### Frontend

- HTML
- CSS
- JavaScript
- Anna App UI SDK

### Backend & AI

- Python
- Anna Executa
- JSON-RPC
- Anna Protocol v2
- Reverse Sampling
- Anna LLM Runtime

### Development

- Anna CLI
- Anna App Harness
- Git
- GitHub

---

## Architecture

The frontend communicates with the Python Executa through Anna's App Runtime:

```javascript
anna.tools.invoke({
  tool_id: "...",
  method: "summarize",
  args: {
    text: "..."
  }
});
```

The Executa receives the text and requests an LLM completion through Anna's reverse Sampling protocol:

```text
sampling/createMessage
```

The Anna host runtime handles the model request and returns the generated summary to the Executa, which then sends the result back to the frontend.

This architecture keeps the application independent from direct integrations with model providers such as OpenAI, Gemini, or Anthropic.

---

## Project Structure

```text
anna-text-summarizer/
│
├── bundle/
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── executas/
│   └── my-first-anna-app/
│       ├── my_first_anna_app_plugin.py
│       ├── pyproject.toml
│       └── uv.lock
│
├── .anna/
├── .gitignore
├── app.json
├── manifest.json
└── README.md
```

### Key Files

**`bundle/index.html`**  
Defines the main application interface.

**`bundle/app.js`**  
Handles input validation, UI state, Executa invocation, errors, and rendering the generated summary.

**`bundle/style.css`**  
Contains the responsive visual design and application styling.

**`executas/my-first-anna-app/my_first_anna_app_plugin.py`**  
Implements the Python Executa, including Protocol v2 negotiation, the `summarize` tool, the `ping` smoke test, and reverse Sampling communication.

**`manifest.json`**  
Defines the Anna App configuration, required Executa, UI permissions, and LLM capabilities.

---

## Anna LLM Capabilities

The application uses Anna's native platform capabilities for AI generation.

### Reverse Sampling Capability

```json
"host_capabilities": [
  "llm.sample"
]
```

### LLM Host Permission

```json
"llm": [
  "complete"
]
```

These permissions enable the Python Executa to request LLM generation through the Anna runtime.

---

## Local Development

### Prerequisites

- Node.js 22+
- npm
- Python
- `uv`
- Anna CLI
- Anna developer account
- Anna Local Agent

Install the Anna CLI:

```bash
npm install -g @anna-ai/cli
```

Authenticate with Anna:

```bash
anna-app login --host https://anna.partners
```

Confirm the authenticated account:

```bash
anna-app whoami
```

---

## Run Locally

Clone the repository:

```bash
git clone https://github.com/mahtabb90/anna-text-summarizer.git
cd anna-text-summarizer
```

Validate the application:

```bash
anna-app validate
```

Run strict validation:

```bash
anna-app validate --strict
```

Start the local Anna App Harness:

```bash
anna-app dev
```

The local development dashboard will normally be available at:

```text
http://localhost:5180
```

Open the app in the harness, paste text into the input field, and select **Generate Summary**.

---

## Validation

The project has been verified successfully with:

```bash
anna-app validate
```

and:

```bash
anna-app validate --strict
```

The complete local AI workflow has also been tested successfully:

```text
Frontend
→ Anna Runtime
→ Python Executa
→ Reverse Sampling
→ Anna LLM
→ Summary returned
→ Summary displayed in UI
```

---

## Security & API Keys

This project does **not** contain or require direct OpenAI, Gemini, Anthropic, or other third-party LLM API keys.

AI generation is handled through Anna's runtime using reverse Sampling.

Local credentials and development registration files are excluded from version control where appropriate.

Generated LLM content is rendered safely as text rather than injected as raw HTML.

---

## Error Handling

The application includes handling for:

- empty input
- excessively long input
- LLM request timeouts
- unavailable sampling capability
- quota-related failures
- host runtime errors
- duplicate submissions

Errors are converted into clear user-facing messages in the interface.

---

## Project Status

**Functional local implementation**

The core summarization workflow is complete and successfully runs through the Anna local development environment.

Current capabilities include:

- working Anna App UI
- working Python Executa
- working reverse Sampling
- successful LLM-generated summaries
- manifest validation
- strict validation
- responsive frontend
- loading and error states
- copy-to-clipboard functionality

Future work may include additional summarization modes, further UX improvements, and preparation for publishing through the Anna platform.

---

## About This Project

This project was created as a hands-on exploration of building AI applications on **Anna AI OS**, with a focus on understanding the complete application architecture rather than simply calling an external LLM API.

It demonstrates how frontend interactions, Executa tools, runtime permissions, protocol negotiation, reverse RPC, and hosted LLM capabilities work together inside the Anna ecosystem.

---

## Author

**Mahtab Nezam**  
AI Developer

GitHub: [@mahtabb90](https://github.com/mahtabb90)

---

## Resources

- [Anna Developer Hub](https://anna.partners/developers/overview/welcome)
- [Anna Forum](https://forum.anna.partners/)