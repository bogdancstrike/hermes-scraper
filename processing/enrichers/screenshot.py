"""
Screenshot enricher — captures a full-page screenshot via Playwright.
Enabled via CAPTURE_SCREENSHOT=True.

Screenshots are saved to:
  output/{domain}/screenshots/{YYYYMMDD}/{slug}.{ext}

Returns the path to the saved screenshot or None on failure.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from shared.logging import get_logger

logger = get_logger("screenshot")

_SLUG_RE = re.compile(r'[^a-zA-Z0-9\-_]')


def _url_to_slug(url: str, max_len: int = 80) -> str:
    """Convert a URL to a filesystem-safe slug."""
    # Strip protocol + domain, keep path
    slug = re.sub(r'^https?://[^/]+', '', url).strip("/").replace("/", "-")
    slug = _SLUG_RE.sub('_', slug)[:max_len] or "article"
    return slug


async def capture_screenshot(
    page,  # Playwright Page object
    url: str,
    output_dir: Path,
    domain: str,
    screenshot_type: str = "jpeg",
) -> str | None:
    """
    Take a full-page screenshot of the currently loaded Playwright page.

    Args:
        page:            Playwright Page object (must already have url loaded).
        url:             Article URL (used for filename).
        output_dir:      Root output directory (e.g. Path("output")).
        domain:          Site domain (e.g. "euronews.ro").
        screenshot_type: "jpeg" or "png".

    Returns:
        Absolute path string to the saved screenshot, or None on failure.
    """
    ext = "jpg" if screenshot_type == "jpeg" else "png"
    date_str = datetime.utcnow().strftime("%Y%m%d")
    slug = _url_to_slug(url)
    dest_dir = output_dir / domain / "screenshots" / date_str
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slug}.{ext}"

    try:
        await page.screenshot(
            path=str(dest),
            full_page=True,
            type=screenshot_type,
            quality=80 if screenshot_type == "jpeg" else None,
        )
        logger.debug("screenshot_saved", url=url, path=str(dest))
        return str(dest)
    except Exception as exc:
        logger.warning("screenshot_failed", url=url, error=str(exc))
        return None
