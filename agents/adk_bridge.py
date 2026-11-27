"""Optional Google ADK bridge. Falls back cleanly when google-adk is not installed."""

from __future__ import annotations

from typing import List, Optional

from core.config import get_settings

try:
    from google.adk.agents import Agent as AdkAgent
    ADK_AVAILABLE = True
except ImportError:
    AdkAgent = None  # type: ignore
    ADK_AVAILABLE = False


def build_adk_agent_tree(specialist_names: List[str]) -> Optional[object]:
    """Constructs a read-only/tool-scoped Google ADK LlmAgent tree when google-adk & GEMINI_API_KEY are configured."""
    settings = get_settings()
    if not (settings.deskmate_use_adk and ADK_AVAILABLE and settings.gemini_api_key):
        return None

    sub_agents = [
        AdkAgent(
            name=name,
            model=settings.llm_model or "gemini-2.0-flash",
            instruction=f"You are {name}. Stay strictly inside your DeskMate permission boundary.",
        )
        for name in specialist_names
    ]
    return AdkAgent(
        name="DeskMateOrchestrator",
        model=settings.llm_model or "gemini-2.0-flash",
        instruction="Delegate user requests to the single most appropriate specialist sub-agent.",
        sub_agents=sub_agents,
    )
