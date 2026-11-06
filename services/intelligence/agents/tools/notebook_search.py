"""Follow-up access to the same archive used by automatic report grounding."""

from langchain_core.tools import ToolException, tool

from rag.evidence import pack_with_lineage
from rag.notebooks import NOTEBOOK_EVIDENCE_MAX_CHARS, notebook_context


@tool(response_format="content_and_artifact")
async def notebook_search(query: str) -> tuple[str, list[dict]]:
    """Find original NotebookLM passages for a focused follow-up question.

    Returns attributed background and separately marked methods. These are not
    current-event confirmations or location observations, even in a scoped run.
    Unknown publication dates remain unknown; source assertions need checking.
    """
    try:
        items = await notebook_context(query)
        if not items:
            return "NO_NOTEBOOK_MATCHES: no matching archive passages.", []
        return pack_with_lineage(items, budget=NOTEBOOK_EVIDENCE_MAX_CHARS, preserve_order=True)
    except Exception as exc:
        raise ToolException("Notebook archive retrieval failed") from exc
