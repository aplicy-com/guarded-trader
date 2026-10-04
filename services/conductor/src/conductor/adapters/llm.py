"""LLM interface stubs. Neither backend is implemented in 3A-1 (research loop is 3B).

Both will be text-in/text-out only: no tools, no exchange access (ADR-0003).
"""

from conductor.application.ports import LlmClient


class ClaudeCodeHeadlessClient:
    """Future: shell out to `claude -p` (headless Claude Code)."""

    def complete(self, prompt: str) -> str:
        raise NotImplementedError("claude-code-headless backend is not implemented yet (3B)")


class AnthropicApiClient:
    """Future: Anthropic Messages API via httpx/SDK, subject to the R6 budget ceiling."""

    def complete(self, prompt: str) -> str:
        raise NotImplementedError("anthropic-api backend is not implemented yet (3B)")


def build_llm_client(backend: str) -> LlmClient | None:
    match backend:
        case "none":
            return None
        case "claude_code_headless":
            return ClaudeCodeHeadlessClient()
        case "anthropic_api":
            return AnthropicApiClient()
        case _:
            raise ValueError(f"unknown llm backend: {backend}")
