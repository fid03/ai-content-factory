"""
research_real.py — real web mənbələri (DuckDuckGo, açarsız).
pip install ddgs   (köhnə ad: duckduckgo_search)
Search alınmasa boş siyahı qaytarır (crash olmur) — LLM yenə işləyir.
"""
def search_sources(query, k=6):
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        out = []
        with DDGS() as d:
            for r in d.text(query, max_results=k):
                out.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", "") or r.get("url", ""),
                    "snippet": r.get("body", "") or r.get("snippet", ""),
                })
        return out
    except Exception as e:
        print("search_sources error:", e)
        return []