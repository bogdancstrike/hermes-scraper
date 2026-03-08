"""
All LLM prompt templates in one place.
Keeping prompts centralized makes them easy to tune and version.
"""

SELECTOR_DISCOVERY_SYSTEM = """You are an expert web scraping engineer with deep knowledge of CSS selectors and HTML structure.
Your task is to analyze an HTML DOM snapshot and identify the CSS selectors for key page elements.
You must return ONLY valid JSON. No explanation, no markdown, no code blocks — pure JSON only.

RULES FOR WRITING SELECTORS:
1. Prefer semantic HTML elements: article, main, section, nav, h1, h2, h3, time, address.
2. Prefer id attributes (#my-id) and data-* attributes ([data-foo]).
3. Use short, stable class names (e.g. .article, .post-title, .author). Max 2 classes per selector.
4. NEVER use Tailwind or utility CSS classes — these are invalid for scraping:
   - Classes containing ":" (e.g. hover:text-blue, md:flex, dark:text-white)
   - Classes containing "[" or "]" (e.g. text-[14px], w-[200px])
   - Single-purpose utilities: flex, grid, block, hidden, relative, absolute, overflow, items-center,
     justify-, text-sm, font-, px-, py-, mx-, my-, w-, h-, bg-, border-, rounded-, shadow-, z-
5. If no stable selector exists, return "".
6. Selectors must be valid CSS — test mentally before returning."""

SELECTOR_DISCOVERY_USER = """Analyze this HTML DOM and return CSS selectors for the following elements:
- article_links_selector: CSS selector for links to individual articles/posts on a listing page
- pagination_next_selector: CSS selector for the "next page" link
- article_body_selector: CSS selector for the main article body content
- article_title_selector: CSS selector for the article title
- article_date_selector: CSS selector for the publication date
- author_selector: CSS selector for the author name

Return this exact JSON schema (use empty string "" for elements not found):
{{
  "article_links_selector": "...",
  "pagination_next_selector": "...",
  "article_body_selector": "...",
  "article_title_selector": "...",
  "article_date_selector": "...",
  "author_selector": "...",
  "confidence": 0.9
}}

Domain: {domain}
Sample URL: {sample_url}

HTML DOM:
{dom}"""



ROBOTS_CHECK_PROMPT = """Given this robots.txt content and a URL path, determine if scraping is allowed.
Return JSON: {{"allowed": true/false, "reason": "brief explanation"}}

Robots.txt:
{robots_txt}

URL path to check: {path}"""
