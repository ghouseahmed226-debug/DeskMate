"""ResearchIntelligenceAgent: grounded web research and fact verification with honest offline fallback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests
from sqlalchemy.orm import Session

from agents.base import AgentTaskInput, AgentTaskOutput, BaseSpecialistAgent
from core.security import wrap_untrusted_data


class ResearchIntelligenceAgent(BaseSpecialistAgent):
    name = "ResearchIntelligenceAgent"
    category = "research"
    description = "Web research, company/market lookup, and source verification without fabricating citations."
    instruction_filename = "research_intelligence.md"

    def execute(self, task: AgentTaskInput, session: Optional[Session] = None) -> AgentTaskOutput:
        self.assert_no_loop(task)
        self.check_tool_permission(session, task, "web_search", task.params)

        query = (task.params.get("query") or task.raw_query or "").strip()
        if not query:
            return AgentTaskOutput(
                agent_name=self.name,
                status="needs_clarification",
                message="A research topic or URL is required.",
                clarification_question="What topic, company, or question should I research?",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        sources: List[Dict[str, Any]] = []
        live_status = "offline_or_unreachable"

        try:
            resp = requests.get(
                f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1",
                timeout=6,
                headers={"User-Agent": "DeskMateAI/2.0"},
            )
            if resp.status_code == 200:
                payload = resp.json()
                abstract = (payload.get("AbstractText") or "").strip()
                abstract_url = (payload.get("AbstractURL") or "").strip()
                if abstract and abstract_url:
                    sources.append(
                        {
                            "title": payload.get("Heading") or query,
                            "url": abstract_url,
                            "snippet": abstract,
                            "retrieved_at": now_iso,
                            "type": "verified_web_abstract",
                        }
                    )
                for topic in payload.get("RelatedTopics", [])[:4]:
                    if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                        sources.append(
                            {
                                "title": topic.get("Text", "")[:90],
                                "url": topic["FirstURL"],
                                "snippet": topic["Text"],
                                "retrieved_at": now_iso,
                                "type": "verified_web_reference",
                            }
                        )
                live_status = "live_web_queried"
        except Exception:
            live_status = "offline_or_network_blocked"

        self.log_tool_use(
            session,
            task,
            "web_search",
            params={"query": query, "live_status": live_status, "sources_found": len(sources)},
        )

        if sources:
            bullet_lines = [
                f"- [{s['title']}]({s['url']}) ({s['retrieved_at']}): {wrap_untrusted_data('web', s['snippet'][:220])}"
                for s in sources
            ]
            msg = (
                f"### Research Summary: {query}\n"
                "**Verified Sources:**\n"
                + "\n".join(bullet_lines)
                + "\n\n**Next Steps / Caveat:** Review cited primary URLs directly for complete legal or financial decisions."
            )
        else:
            msg = (
                f"### Research Status for '{query}'\n"
                "- **Verified External Sources:** None retrieved (live web search is unavailable or returned zero verified results).\n"
                "- **Policy Enforcement:** DeskMate refuses to fabricate URLs, statistics, or dates.\n"
                "- **Recommended Action:** Connect an external web-search integration or enable outbound network access for live citations."
            )

        return AgentTaskOutput(
            agent_name=self.name,
            message=msg,
            data={"query": query, "live_status": live_status, "sources": sources},
            tools_called=["web_search"],
        )
