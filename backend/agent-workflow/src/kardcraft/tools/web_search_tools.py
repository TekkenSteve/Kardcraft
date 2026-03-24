"""Web Search Tools - Quick research capability for syllabus_agent.

This module provides web search functionality as a Tool that can be called
 directly from syllabus_agent, eliminating the need for next_step routing.

Usage:
    from kardcraft.tools import quick_research
    result = await quick_research.ainvoke({"query": "your search query"})
"""

from typing import Dict, Any
from langchain_core.tools import tool

from kardcraft.utils.logger import logger
from kardcraft.utils.web_utils import tavily_search_raw, filter_web_results, ALLOWLIST_DOMAINS

# TEMP: mock web search to avoid Tavily usage while testing the pipeline.
# Set to True to bypass external calls.
MOCK_WEB_SEARCH = False

# Captured real Tavily results for the query:
# "history 你能帮我制作三国人物的闪卡吗?包括人物背景"
MOCK_WEB_RESULTS = [
    {
        "title": "三国杀- 萌娘百科万物皆可萌的百科全书",
        "url": "https://zh.moegirl.org.cn/%E4%B8%89%E5%9B%BD%E6%9D%80",
        "content": """三国杀 - 萌娘百科 万物皆可萌的百科全书

This site requires JavaScript enabled. Please check your browser settings.

[![](https://storage.moegirl.org.cn/moegirl/commons/4/47/Sanguoshalogo.png!/fw/99?v=20200723080727)](/%E4%B8%89%E5%9B%BD%E6%9D%80 \"三国杀\")

**萌娘百科欢迎您参与完善本条目☆杀！   
墨守成规，不如改而缮之！欢迎有兴趣编辑讨论的朋友加入[萌娘百科三国杀编辑组](/Template:%E8%90%8C%E5%A8%98%E7%99%BE%E7%A7%91%E4%B8%89%E5%9B%BD%E6%9D%80%E7%BC%96%E8%BE%91%E7%BB%84 \"Template:萌娘百科三国杀编辑组\")，并请在编辑前阅读[专题编辑指南](/Help:%E4%B8%89%E5%9B%BD%E6%9D%80%E4%B8%93%E9%A2%98%E7%BC%96%E8%BE%91%E6%8C%87%E5%8D%97 \"Help:三国杀专题编辑指南\")。**  
可以从以下几个方面加以改进：

* 资料部分过时

欢迎正在阅读这个条目的您协助[编辑本条目](https://mzh.moegirl.org.cn/index.php?title=%E4%B8%89%E5%9B%BD%E6%9D%80&action=edit)。编辑前请阅读[Wiki入门](/Help:%E4%B8%89%E5%9B%BD%E6%9D%80%E4%B8%93%E9%A2%98%E7%BC%96%E8%BE%91%E6%8C%87%E5%8D%97 \"Help:Wiki入门\")或[条目编辑规范](/%E8%90%8C%E5%A8%98%E7%99%BE%E7%A7%91:%E7%BC%96%E8%BE%91%E8%A7%84%E8%8C%83 \"萌娘百科:编辑规范\")，并查找相关资料。萌娘百科祝您在本站度过愉快的时光。

![](https://storage.moegirl.org.cn/moegirl/commons/8/8f/%E4%B8%89%E5%9B%BD%E6%9D%80background.jpg)

|  |  |  |
| --- | --- | --- |
| “ | 我们的游戏正在蒸蒸日上哦！ | ” |

|  |  |
| --- | --- |
|  | |
| **基本资料** | |
| 作品原名 | 三国杀 |
| 作品译名 | Legends of the Three Kingdoms |
| 原作载体 | 桌面游戏 |
| 原作作者 | 游卡网络 |
| 改编载体 | 在线游戏、漫画、其他桌游等 |
| 相关作品 | 《[阵面对决](/index.php?title=%E9%98%B5%E9%9D%A2%E5%AF%B9%E5%86%B3&action=edit&redlink=1 \"阵面对决（页面不存在）\")》等 |

**《三国杀》**是由[游卡网络](/%E6%B8%B8%E5%8D%A1%E7%BD%91%E7%BB%9C \"游卡网络\")开发的桌面游戏。
""",
        "score": 0.9869795,
    },
    {
        "title": "melhores sites de apostas aviator：权威平台开放，畅享全新服务 ...",
        "url": "http://www.gyjsxy.com/show.php/le5mxlad.html",
        "content": """Error fetching content from http://www.gyjsxy.com/show.php/le5mxlad.html: Client error '404 Not Found' for url 'http://www.gyjsxy.com/show.php/le5mxlad.html'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404""",
        "score": 0.7839885,
    },
    {
        "title": "好用的娱乐赛事app:福彩助手手机客户端 - 珍爱网",
        "url": "https://m.zhenai.com/y/tmec/26362871.html",
        "content": """404 页面不存在



404 您访问的页面不存在""",
        "score": 0.0028338498,
    },
]

@tool(parse_docstring=True)
async def quick_research(
    query: str,
    max_results: int = 5,
    topic: str = "general",
) -> Dict[str, Any]:
    """Quick web search for syllabus_agent -补充知识库不足的信息.

    与 knowledge_tools 的区别：
    - knowledge_tools: 查询本地知识库（RAG）
    - quick_research: 上网搜索最新信息

    使用 Tavily API 搜索网页并获取完整内容。

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return (default: 5)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

    Returns:
        Dict with keys: List of result:
        - results dicts with title, url, content, score
        - query: The query that was executed
        - topic: Topic filter used
        - error: Error message if failed (absent if successful)
    """
    logger.info(
        "quick_research tool called",
        query=query[:100],
        max_results=max_results,
        topic=topic,
    )

    if MOCK_WEB_SEARCH:
        logger.info("quick_research using MOCK result")
        mock_results = filter_web_results(MOCK_WEB_RESULTS)
        if not mock_results:
            logger.warning("No allowlisted mock results; returning empty set")
            return {
                "results": [],
                "query": query,
                "topic": topic,
                "error": "no_allowlisted_results",
            }
        return {
            "results": mock_results[:max_results],
            "query": query,
            "topic": topic,
        }

    real_results = await tavily_search_raw(query, max_results, topic)
    if isinstance(real_results, dict) and real_results.get("results"):
        filtered = filter_web_results(real_results["results"])
        if filtered:
            real_results["results"] = filtered[:max_results]
        else:
            real_results["results"] = []
            real_results["error"] = "no_allowlisted_results"
    return real_results


# Export list for easy importing
web_search_tools = [quick_research]
