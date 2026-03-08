"""
POST /v1/analyze-selectors — CSS selector discovery endpoint.
"""
from fastapi import APIRouter, HTTPException
from llm_api.llm_client import get_llm_client
from llm_api.prompts import SELECTOR_DISCOVERY_SYSTEM, SELECTOR_DISCOVERY_USER
from shared.logging import get_logger
from shared.models import SelectorRequest, SelectorResponse

router = APIRouter()
logger = get_logger("selectors_router")


@router.post("/analyze-selectors", response_model=SelectorResponse)
async def analyze_selectors(req: SelectorRequest) -> SelectorResponse:
    """
    Analyze an HTML DOM snapshot and return CSS selectors for key elements.
    Result should be cached by the calling scraper node.
    """
    if not req.dom:
        raise HTTPException(status_code=422, detail="DOM content is required")

    client = get_llm_client()

    user_prompt = SELECTOR_DISCOVERY_USER.format(
        domain=req.domain,
        sample_url=req.sample_url or "",
        dom=req.dom[:4000],
    )

    try:
        raw_text, model_name = await client.complete(
            system_prompt=SELECTOR_DISCOVERY_SYSTEM,
            user_prompt=user_prompt,
            endpoint_label="analyze-selectors",
        )
        data = client.parse_json_response(raw_text)
    except Exception as exc:
        logger.error("selector_analysis_failed", domain=req.domain, error=str(exc))
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    logger.info("selectors_discovered", domain=req.domain, model=model_name)

    return SelectorResponse(
        article_links_selector=data.get("article_links_selector", ""),
        pagination_next_selector=data.get("pagination_next_selector", ""),
        article_body_selector=data.get("article_body_selector", ""),
        article_title_selector=data.get("article_title_selector", ""),
        article_date_selector=data.get("article_date_selector", ""),
        author_selector=data.get("author_selector", ""),
        confidence=float(data.get("confidence", 0.8)),
        model_used=model_name,
    )
