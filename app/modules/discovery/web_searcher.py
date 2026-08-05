"""
Module 1 — Web Searcher
Multi-tier search: Tavily → DuckDuckGo (via ddgs lib) → direct Bing scrape → direct DDG Lite.
Filters out draft/consultation and non-country-specific results before returning.
"""
import logging
import time
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger(__name__)

EXCLUDED_KEYWORDS = [
    "draft", "consultation paper", "proposed", "discussion paper",
    "green paper", "white paper consultation", "bill introduced",
    "exposure draft", "call for submissions",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# International org domains always relevant regardless of target country
INTERNATIONAL_ORG_DOMAINS = [
    "wto.org", "unctad.org", "worldbank.org", "oecd.org",
    "wipo.int", "itu.int", "asean.org", "apec.org", "imf.org",
    "un.org", "unctad",
]

# Social media / video — never relevant for regulatory document discovery
EXCLUDED_DOMAINS = [
    "youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "linkedin.com", "tiktok.com", "reddit.com",
    "pinterest.com", "snapchat.com", "tumblr.com",
]

COUNTRY_TLDS = {
    "singapore": [".sg", ".gov.sg"],
    "malaysia": [".my", ".gov.my"],
    "australia": [".au", ".gov.au"],
}


def _is_country_relevant(url: str, country: str) -> bool:
    """Return False for URLs clearly unrelated to the target country.
    
    Only filters out:
    - Social/video domains (always irrelevant)
    - Other countries' government domains (to avoid cross-country contamination)
    
    Allows through:
    - International organisations (wto.org, unctad.org, etc.)
    - Target country's own TLDs
    - Any URL containing the country name
    - Generic .com/.org/.net domains (secondary sources classified later)
    """
    if not country:
        return True
    url_lower = url.lower()
    netloc = urlparse(url).netloc.lower()
    domain = netloc[4:] if netloc.startswith("www.") else netloc

    # Exclude social / video domains outright
    if any(exc in domain for exc in EXCLUDED_DOMAINS):
        return False

    # Always allow international organisations
    if any(org in domain for org in INTERNATIONAL_ORG_DOMAINS):
        return True

    country_lower = country.strip().lower()

    # Country name appears anywhere in the URL
    if country_lower in url_lower:
        return True

    # Country-specific top-level domain
    tlds = COUNTRY_TLDS.get(country_lower, [])
    if tlds and any(domain.endswith(tld) for tld in tlds):
        return True

    # Explicitly reject *other* countries' government domains
    # (e.g. a Singapore query shouldn't pull in Malaysian .gov.my pages)
    all_country_tlds = {tld for tlds_list in COUNTRY_TLDS.values() for tld in tlds_list}
    if any(domain.endswith(tld) for tld in all_country_tlds):
        return False  # belongs to a different country's official domain

    # Allow generic domains (.com, .org, .net, .io etc.) through —
    # they may reference the target country's laws even if the URL doesn't
    # include the country name. The URL classifier will label them SECONDARY_LEAD.
    return True


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    query_used: str
    strategy: str


def _is_excluded(snippet: str, title: str) -> bool:
    combined = (snippet + " " + title).lower()
    return any(kw in combined for kw in EXCLUDED_KEYWORDS)


# ─── Tier 1: DuckDuckGo via duckduckgo_search library ───────────────────────

def _search_duckduckgo_search(query: str, max_results: int) -> list[SearchResult] | None:
    """Try the old duckduckgo_search library."""
    try:
        from duckduckgo_search import DDGS
        results: list[SearchResult] = []
        with DDGS(timeout=10) as ddgs:
            raw = ddgs.text(query, max_results=max_results)
            for r in raw:
                url = r.get("href", "")
                title = r.get("title", "")
                snippet = r.get("body", "")
                if not url:
                    continue
                if _is_excluded(snippet, title):
                    continue
                results.append(SearchResult(url, title, snippet, query, "ddgs_old"))
        if results:
            return results
    except Exception as exc:
        logger.debug(f"[Search] duckduckgo_search lib failed: {exc}")
    return None


# ─── Tier 3: Direct Bing HTML scrape ───────────────────────────────────────

def _search_bing(query: str, max_results: int) -> list[SearchResult] | None:
    """Scrape Bing search results directly with httpx + BeautifulSoup.
    Uses multiple selector strategies to handle Bing HTML changes.
    """
    try:
        url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max_results}"
        resp = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[SearchResult] = []

        # Strategy 1: Standard result items (li.b_algo, li.b_algo_open)
        for li in soup.select("li.b_algo, li.b_algo_open"):
            link = li.select_one("h2 a")
            if not link:
                continue
            href = link.get("href", "")
            title = link.get_text(strip=True)
            snippet_el = li.select_one(".b_caption p")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if not href or not title:
                continue
            if _is_excluded(snippet, title):
                continue
            results.append(SearchResult(href, title, snippet, query, "bing"))

        # Strategy 2: Fallback — any h2 > a in #b_results
        if not results:
            for link in soup.select("#b_results h2 a"):
                href = link.get("href", "")
                title = link.get_text(strip=True)
                snippet = ""
                parent_li = link.find_parent("li")
                if parent_li:
                    p = parent_li.select_one(".b_caption p, .b_lineclamp2, p")
                    if p:
                        snippet = p.get_text(strip=True)
                if href and title and not _is_excluded(snippet, title):
                    results.append(SearchResult(href, title, snippet, query, "bing"))

        # Strategy 3: Last resort — any <a> with href starting with http inside #b_results
        if not results:
            for a in soup.select("#b_results a[href^=http]"):
                href = a.get("href", "")
                title = a.get_text(strip=True)
                if not href or not title or len(title) < 10:
                    continue
                if _is_excluded("", title):
                    continue
                results.append(SearchResult(href, title, "", query, "bing"))
                if len(results) >= max_results:
                    break

        if results:
            return results
    except Exception as exc:
        logger.debug(f"[Search] Bing scrape failed: {exc}")
    return None


# ─── Tier 4: Direct DuckDuckGo Lite scrape ─────────────────────────────────

def _search_ddg_lite(query: str, max_results: int) -> list[SearchResult] | None:
    """Scrape DuckDuckGo Lite (text-only version) directly."""
    try:
        url = "https://lite.duckduckgo.com/lite/"
        data = {"q": query}
        resp = httpx.post(url, data=data, headers=HEADERS, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[SearchResult] = []

        # DDG Lite results are in <a> tags with class result-link
        for link in soup.select("a.result-link"):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if not href or not title:
                continue
            # Find the sibling snippet
            snippet_el = link.find_next("td", class_="result-snippet")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if _is_excluded(snippet, title):
                continue
            results.append(SearchResult(href, title, snippet, query, "ddg_lite"))
            if len(results) >= max_results:
                break

        if results:
            return results
    except Exception as exc:
        logger.debug(f"[Search] DDG Lite scrape failed: {exc}")
    return None


# ─── Tier 0: Tavily API (primary when key is set) ─────────────────────────

def _search_tavily(query: str, max_results: int) -> list[SearchResult] | None:
    """Search via Tavily API — requires TAVILY_API_KEY in .env."""
    api_key = settings.tavily_api_key
    if not api_key:
        return None
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
        )
        results = []
        for r in response.get("results", []):
            url = r.get("url", "")
            title = r.get("title", "")
            snippet = r.get("content", "")
            if not url or not title:
                continue
            if _is_excluded(snippet, title):
                continue
            results.append(SearchResult(url, title, snippet, query, "tavily"))
        if results:
            return results
    except Exception as exc:
        logger.debug(f"[Search] Tavily failed: {exc}")
    return None


# ─── Tier 5: Direct Google HTML scrape (last resort) ──────────────────────

def _search_google(query: str, max_results: int) -> list[SearchResult] | None:
    """Scrape Google search results directly with httpx + BeautifulSoup."""
    try:
        url = f"https://www.google.com/search?q={quote_plus(query)}&num={max_results}"
        google_headers = {**HEADERS, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        resp = httpx.get(url, headers=google_headers, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[SearchResult] = []
        seen: set[str] = set()

        def _extract_google_url(href: str) -> str | None:
            """Extract the actual URL from a Google search result redirect link."""
            if href.startswith("/url?q="):
                from urllib.parse import parse_qs
                qs = parse_qs(urlparse(href).query)
                return qs.get("q", [None])[0]
            return href if href.startswith("http") else None

        # Strategy 1: Standard organic results — h3 > a inside result divs
        for result_div in soup.select("div.g, div[data-hveid]"):
            link = result_div.select_one("h3 a")
            if not link:
                link = result_div.select_one("a[href^='/url?q=']")
            if not link:
                continue
            href = link.get("href", "")
            title = link.get_text(strip=True)
            actual_url = _extract_google_url(href)
            if not actual_url or not title or actual_url in seen:
                continue
            seen.add(actual_url)
            snippet_el = result_div.select_one("div[data-sncf], span.aCOpRe, div.VwiC3b, div.lEBKkf")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if _is_excluded(snippet, title):
                continue
            results.append(SearchResult(actual_url, title, snippet, query, "google"))
            if len(results) >= max_results:
                break

        if results:
            return results
    except Exception as exc:
        logger.debug(f"[Search] Google scrape failed: {exc}")
    return None


# ─── Search tiers ──────────────────────────────────────────────────────────

SEARCH_TIERS = [
    ("tavily",            _search_tavily),
    ("duckduckgo_search", _search_duckduckgo_search),
    ("bing_html",         _search_bing),
    ("ddg_lite",          _search_ddg_lite),
    ("google_web",        _search_google),
]


def search_web(query: str, strategy: str, max_results: int = 10) -> list[SearchResult]:
    """
    Execute a single search query across multiple backends.
    Returns filtered results excluding drafts/consultations.

    For portal/government strategies, ALL tiers are tried and results are
    merged (deduped by URL).  For other strategies, the first tier with
    results wins.
    """
    multistrategies = {"portal_targeted", "legislation_portal", "gov_targeted",
                       "full_act_pdf", "amendment_check", "portal_direct"}

    seen_urls: set[str] = set()
    merged: list[SearchResult] = []

    for tier_name, tier_fn in SEARCH_TIERS:
        try:
            results = tier_fn(query, max_results)
        except Exception as exc:
            logger.debug(f"[Search] {tier_name} failed: {exc}")
            continue

        if not results:
            continue

        # Deduplicate against all previously seen URLs
        fresh = []
        for r in results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                fresh.append(r)

        if not fresh:
            continue

        for r in fresh:
            r.strategy = strategy
            r.query_used = query
        merged.extend(fresh)

        logger.info(
            f"[Search] '{strategy}' got {len(fresh)} new results via {tier_name} "
            f"for: {query[:80]}"
        )

        if strategy not in multistrategies:
            # Non-portal strategies stop at first non-empty tier
            break

    if merged:
        logger.info(f"[Search] '{strategy}' total merged: {len(merged)} for: {query[:80]}")
        return merged

    logger.warning(f"[Search] '{strategy}' returned 0 results for: {query[:80]}")
    return []


def search_queries(
    country: str,
    queries: list,
    max_results_per_query: int = 10,
    min_primary_threshold: int = 2,
) -> list[SearchResult]:
    """
    Execute multiple queries in priority order.
    Filters results by country relevance and stops early at Q6+
    if enough primary-source candidates found in Q1-Q5.
    """
    seen_urls: set[str] = set()
    all_results: list[SearchResult] = []
    gov_count = 0

    for q in sorted(queries, key=lambda x: x.priority):
        results = search_web(q.query_string, q.strategy, max_results_per_query)

        for r in results:
            if not _is_country_relevant(r.url, country):
                logger.debug(f"[Search] Filtered out (not relevant to {country}): {r.url}")
                continue
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            all_results.append(r)
            # Count primary-source (.gov) results for early-stop logic
            r_domain = urlparse(r.url).netloc.lower()
            if r_domain.startswith("www."):
                r_domain = r_domain[4:]
            country_tld = COUNTRY_TLDS.get(country.strip().lower(), [])
            if country_tld and any(r_domain.endswith(tld) for tld in country_tld):
                gov_count += 1
            elif ".gov." in r_domain or r_domain.endswith(".gov"):
                gov_count += 1

        # Never early-stop portal-targeted or gov-targeted queries —
        # these are most likely to find sectoral laws (e.g. My Health Records Act).
        always_run = {"portal_targeted", "legislation_portal", "gov_targeted", "full_act_pdf", "amendment_check"}
        if q.priority >= 5 and gov_count >= min_primary_threshold and q.strategy not in always_run:
            logger.info(
                f"[Search] Early stop after priority {q.priority} — "
                f"{gov_count} primary-source candidates found."
            )
            break

        time.sleep(settings.search_rate_limit_seconds)

    logger.info(f"[Search] Total unique results: {len(all_results)} ({gov_count} .gov)")
    return all_results
