"""Web Search Utilities - Common functionality for web searching and content fetching."""

import os
import httpx
from typing import Dict, Any, List, Optional
from markdownify import markdownify
from kardcraft.utils.logger import logger

# High-quality domains for learning/flashcard content
ALLOWLIST_DOMAINS = {
    "zh.wikipedia.org",
    "en.wikipedia.org",
    "zh.wikisource.org",
    "baike.baidu.com",
    "www.britannica.com",
    "www.history.com",
    "www.nationalgeographic.com",
    "plato.stanford.edu",
    "ctext.org",
}


def filter_web_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered = []
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        for domain in ALLOWLIST_DOMAINS:
            if domain in url:
                filtered.append(r)
                break
    return filtered


def fetch_webpage_content(url: str, timeout: float = 10.0) -> str:
    """Fetch and convert webpage content to markdown.
    
    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds
        
    Returns:
        Markdown representation of the webpage content
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = httpx.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return markdownify(response.text)
    except Exception as e:
        logger.warning(f"Failed to fetch content from {url}", error=str(e))
        return f"Error fetching content from {url}: {str(e)}"


async def tavily_search_raw(
    query: str, max_results: int = 5, topic: str = "general"
) -> Dict[str, Any]:
    """Core Tavily search implementation returning structured data.

    Returns dict with:
    - results: List of search results with content
    - query: The query that was executed
    - topic: Topic used
    - error: Error message if failed
    """
    try:
        from tavily import TavilyClient

        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            return {
                "results": [],
                "query": query,
                "error": "TAVILY_API_KEY not configured",
            }

        client = TavilyClient(api_key=tavily_api_key)

        # Use Tavily to discover URLs (use include_domains for strict filtering)
        search_results = client.search(
            query,
            max_results=max_results,
            topic=topic,
            include_domains=sorted(ALLOWLIST_DOMAINS),
        )

        raw_results = search_results.get("results", [])
        allowlisted_results = filter_web_results(raw_results)

        # Fetch full content for each URL (allowlisted only)
        result_items = []
        for result in allowlisted_results:
            url = result.get("url", "")
            title = result.get("title", "")

            # Fetch webpage content
            content = fetch_webpage_content(url)

            result_items.append(
                {
                    "title": title,
                    "url": url,
                    "content": content,
                    "score": result.get("score", 0),
                }
            )

        # TEMP: log full results for debugging/recording (no truncation)
        logger.info(
            "TAVILY_RAW_RESULTS",
            query=query,
            results=result_items,
        )

        if not result_items:
            logger.warning(
                "Tavily results filtered out by allowlist",
                query=query,
                result_count=len(raw_results),
            )
        else:
            logger.info(
                "Tavily results allowlisted",
                query=query,
                result_count=len(result_items),
            )

        logger.info(
            "Tavily search raw complete",
            query=query[:50],
            result_count=len(result_items),
        )

        return {
            "results": result_items,
            "query": query,
            "topic": topic,
            **({"error": "no_allowlisted_results"} if not result_items else {}),
        }

    except ImportError:
        return {
            "results": [],
            "query": query,
            "error": "tavily-python not installed",
        }
    except Exception as e:
        logger.error("Tavily search failed", error=str(e))
        return {
            "results": [],
            "query": query,
            "error": str(e),
        }
