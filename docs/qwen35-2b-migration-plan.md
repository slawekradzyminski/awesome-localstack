# Qwen 3.5 2B Migration Plan

This document captures the implementation plan for standardizing on `qwen3.5:2b` for both thinking and function calling across:

- `~/IdeaProjects/test-secure-backend`
- `~/IdeaProjects/vite-react-frontend`
- `~/IdeaProjects/awesome-localstack`

It is a migration plan, not just a string replacement, because the current setup is explicitly split between a lightweight thinking model and a separate tools model in docs, hooks, tests, and Docker images.

## Current State

The current split is visible across all three repositories:

- Backend/docs still center on `qwen3:4b-instruct` for chat and tool examples, even though the backend code already accepts arbitrary `model` values together with `think`.
- Frontend defaults:
  - chat: `qwen3:0.6b`
  - generate: `qwen3:0.6b`
  - tools: `qwen3:4b-instruct`
- Infra still bakes an Ollama image around `qwen3:4b-instruct` with `qwen3:0.6b` as an extra model.

## Important Constraint

A full end-to-end migration also touches `~/IdeaProjects/ollama-mock`, because the frontend local-development flow and some tests depend on that mock instead of real Ollama.

That repository is outside the requested three-repo scope, so this plan treats it as an external dependency:

- either update `ollama-mock` separately
- or temporarily bypass it in local verification by running real Ollama

## Phase 1: Infra First (`awesome-localstack`)

Goal: ship one model family and one default runtime target in containerized environments.

### 1. Rebuild the Ollama image around `qwen3.5:2b`

Files:

- `ollama/Dockerfile`
- `ollama/wait-and-pull.sh`
- `ollama/README.md`

Planned changes:

- set `OLLAMA_MODEL=qwen3.5:2b`
- set `OLLAMA_EXTRA_MODELS=""` initially
- keep extra models only if a fallback is explicitly needed later

### 2. Replace the old dual-model default

Files:

- `docker-compose.yml`
- `docker-compose-llm.yml`
- `docker-run-all.sh`

Planned changes:

- stop referencing the old `qwens` image digest as the canonical LLM image
- publish a new image tag or digest that clearly corresponds to the `qwen3.5:2b` setup
- make all real-Ollama compose paths use the same image source

### 3. Update documentation and student materials

Files:

- `README.md`
- `STUDENT_GUIDE.md`
- `ollama/README.md`

Planned changes:

- remove references to `qwen3:0.6b` and `qwen3:4b-instruct` as the default split
- document `qwen3.5:2b` as the default model for chat, generate, and tool calling
- update example `curl` payloads accordingly

### 4. Preserve mock-based topologies unless intentionally retired

Files that should stay unchanged unless the mock strategy is being retired:

- `lightweight-docker-compose.yml`
- `docker-compose.server.yml`

Reason:

- those files intentionally point to `ollama-mock`
- switching them to real Ollama is a separate architectural decision

### Infra Verification

- build the new Ollama image
- start the Ollama service by itself
- verify `qwen3.5:2b` is present in `/api/tags`
- run one `generate`, one `chat`, and one `chat` request with `tools`

## Phase 2: Backend Alignment (`test-secure-backend`)

Goal: keep backend logic mostly intact while making defaults, examples, tests, and tool guidance consistent with `qwen3.5:2b`.

### 1. Update model examples and schema examples

Files:

- `README.md`
- `src/main/java/com/awesome/testing/dto/ollama/ChatRequestDto.java`
- `src/main/java/com/awesome/testing/dto/ollama/GenerateRequestDto.java`
- `src/main/java/com/awesome/testing/dto/ollama/StreamedRequestDto.java`

Planned changes:

- replace example model values with `qwen3.5:2b`
- keep the request contract generic so clients can still override the model if needed

### 2. Rewrite tool and prompt copy that assumes `qwen3:4b-instruct`

Files:

- `src/main/java/com/awesome/testing/service/ollama/OllamaToolDefinitionCatalog.java`
- `src/main/java/com/awesome/testing/controller/OllamaController.java`
- `README.md`

Planned changes:

- remove model-specific guidance like “`qwen3:4b-instruct` hallucinates often”
- replace it with behavior-oriented guidance such as:
  - small local models may hallucinate catalog facts
  - every product answer must be grounded through tool output

### 3. Keep service logic unchanged unless live testing proves otherwise

Files:

- `src/main/java/com/awesome/testing/service/ollama/OllamaService.java`
- `src/main/java/com/awesome/testing/service/ollama/OllamaFunctionCallingService.java`

Reason:

- the backend already supports:
  - `think`
  - streamed `thinking`
  - streamed `tool_calls`
  - tool execution plus replay loop

No structural change is needed unless `qwen3.5:2b` behaves differently in real runs.

### 4. Update backend tests and fixtures

Files:

- `src/test/java/com/awesome/testing/factory/ollama/OllamaRequestFactory.java`
- `src/test/java/com/awesome/testing/factory/ollama/OllamaResponseFactory.java`
- `src/test/java/com/awesome/testing/endpoints/ollama/OllamaMock.java`
- `src/test/java/com/awesome/testing/endpoints/ollama/OllamaChatControllerTest.java`
- `src/test/java/com/awesome/testing/endpoints/ollama/OllamaGenerateControllerTest.java`
- `src/test/java/com/awesome/testing/service/ollama/OllamaFunctionCallingServiceTest.java`
- `src/test/java/com/awesome/testing/service/ollama/OllamaServiceTest.java`

Planned changes:

- update assertions and fixture payloads to use `qwen3.5:2b`
- keep coverage for:
  - `think=false`
  - `think=true`
  - tool call streaming
  - tool replay loop

### 5. Update shell verification scripts

Files:

- `test-ollama-endpoint.sh`
- `scripts/verify-docker.sh`

Planned changes:

- pull and test `qwen3.5:2b`
- keep both non-thinking and thinking checks

### 6. Add one explicit integration test for tools plus `think=true`

Reason:

- the backend already supports it
- the old frontend/docs model split avoided it as a product path
- the new target standardizes on one model for both capabilities

### Backend Verification

- run unit tests for DTOs and services
- run endpoint tests for `/generate`, `/chat`, and `/chat/tools`
- perform a real manual smoke test against actual `qwen3.5:2b`
- confirm the tool loop stays within `MAX_TOOL_CALL_ITERATIONS=3`

## Phase 3: Frontend Unification (`vite-react-frontend`)

Goal: make Chat, Generate, and Tools all default to `qwen3.5:2b`, while keeping the UI clear about thinking and tool-calling behavior.

### 1. Change default model values in all hooks

Files:

- `src/hooks/useOllamaChat.ts`
- `src/hooks/useOllamaGenerate.ts`
- `src/hooks/useOllamaToolChat.ts`

Planned defaults:

- chat: `qwen3.5:2b`
- generate: `qwen3.5:2b`
- tools: `qwen3.5:2b`

### 2. Decide on tool-page thinking UX

Recommendation:

- expose the thinking toggle in Tools as an advanced option
- keep it disabled by default
- preserve transcript support for streamed `thinking`, because the tool hook already supports it

This is the key product decision shift from the current setup, which treats the tool lane as effectively non-thinking.

### 3. Update page copy and highlights

Files:

- `README.md`
- `docs/function-calling-flow.md`
- `src/pages/llm/llmPage.tsx`
- `src/lib/ollamaTools.ts`

Planned changes:

- remove claims that chat/generate and tools require different default models
- document one default model across all three LLM surfaces
- adjust wording around grounded answers so it reflects model behavior instead of old model names

### 4. Update unit tests asserting old defaults

Files:

- `src/hooks/useOllamaChat.test.ts`
- `src/hooks/useOllamaGenerate.test.ts`
- `src/hooks/useOllamaToolChat.test.ts`
- `src/pages/ollama/chatPage.test.tsx`
- `src/pages/ollama/generatePage.test.tsx`
- `src/pages/ollama/toolChatPage.test.tsx`

Planned changes:

- replace old default-model assertions
- keep tests for thinking visibility and SSE accumulation
- keep tests for tool call ordering and transcript rendering

### 5. Update Playwright expectations

Files:

- `e2e/tests/llm.chat.spec.ts`
- `e2e/tests/llm.generate.spec.ts`
- `e2e/tests/llm.tools.spec.ts`

Planned changes:

- replace `qwen3:0.6b` and `qwen3:4b-instruct` expectations with `qwen3.5:2b`
- keep coverage for:
  - thinking in chat
  - thinking in generate
  - tool call ordering in tools

### 6. Revisit mocks and fixtures still emitting old model names

Files:

- `e2e/mocks/ollamaMocks.ts`
- `e2e/mocks/ollamaChatMocks.ts`

Planned changes:

- update mocked event payloads to emit `qwen3.5:2b`
- keep the same streaming shape unless real-model behavior forces changes

Note:

- if the team later moves E2E coverage fully onto real backend plus real Ollama, these mocks become less important

### 7. Update local development documentation

Files:

- `LOCAL_DEVELOPMENT.md`
- `README.md`
- `implementation_plan_llm.md`

Planned changes:

- document the new single-model strategy
- call out that mock-based local flows may still require separate `ollama-mock` updates

### Frontend Verification

- run Vitest for hooks and page-level tests
- run Playwright for chat, generate, and tools
- manually validate that the Tools page can now:
  - use `qwen3.5:2b`
  - optionally stream thinking
  - still render tool call notice, tool result, and final answer in order

## Phase 4: Cross-Repo Integration Sequence

Run the migration in this order:

1. `awesome-localstack`
   - build and publish or locally reference the new Ollama image with `qwen3.5:2b`
2. `test-secure-backend`
   - point at real Ollama and validate all three endpoints
3. `vite-react-frontend`
   - confirm defaults and UI behavior against the updated backend

## Manual Scenarios to Test

- Generate with `think=false`
- Generate with `think=true`
- Chat with `think=true`
- Tools with `think=false`
- Tools with `think=true`
- Tools with a broad catalog question that should trigger multiple tool calls
- Tools with a product-specific question that should trigger a single snapshot call

## Main Risks

- `qwen3.5:2b` may emit fewer or less reliable tool calls than the previous dedicated tool model
- tool-call argument quality may regress before schema validation catches it
- local mock-driven tests may pass while real Ollama behavior differs
- frontend UX may become noisier if the tool lane now also displays thinking traces

## Recommended Acceptance Criteria

Ship the migration only if all of the following hold with real `qwen3.5:2b`:

- `/generate` reliably streams `thinking` when `think=true`
- `/chat` reliably streams `thinking` when `think=true`
- `/chat/tools` produces valid tool calls for the current product prompts
- the model consumes tool outputs and produces grounded final replies
- no UI, tests, or docs still claim chat and tools require different default models

## Out of Scope but Required Soon After

`~/IdeaProjects/ollama-mock`

Reason:

- the local-development and some test paths in `vite-react-frontend` still rely on the deterministic mock
- to make the full developer workflow consistent, that mock should also be updated to speak in terms of `qwen3.5:2b`
