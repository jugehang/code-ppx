"""LLM provider abstraction layer.

Supports three provider types:
1. Local — LM Studio, Ollama (OpenAI-compatible local servers)
2. API — OpenAI, Anthropic, DeepSeek, Azure OpenAI, etc.
3. Plugin — VS Code extensions (Claude Code, Codex) via CLI bridge
"""
