"""
Udemy course scraper v2 — powered by Scrapling.
"""

import asyncio
import json
import re as _re
import urllib.parse

from src.utils.scoring import calculate_udemy_score

_MAX_CONCURRENT_TAGS = 4


class UdemyFetcher:
    """Udemy course scraper using Scrapling for Cloudflare Turnstile bypass."""

    def __init__(self, tags, limit=5, headless=True):
        self.tags = tags
        self.limit = limit
        self.headless = headless
        self.results = {}
        self.blocked_tags = []

    # ── Public API (sync — backward-compatible) ──

    def scrape(self):
        """Sync entry point — runs the async scraper in a NEW event loop."""
        try:
            asyncio.run(self._async_scrape())
        except Exception as e:
            raise RuntimeError(f"Udemy scrape failed: {e}") from e

    # ── Async core ──

    async def _async_scrape(self):
        """Core async scraper — extracts all data from search result cards only."""
        from scrapling.fetchers import AsyncStealthySession

        async with AsyncStealthySession(
            headless=self.headless,
            max_pages=min(len(self.tags), _MAX_CONCURRENT_TAGS) + 1,
        ) as session:
            # First request solves Cloudflare, then scrape remaining tags concurrently
            if not self.tags:
                return

            # Solve Cloudflare on the first tag
            first_tag = self.tags[0]
            print(f"    --- Scraping Udemy (v2): {first_tag} ---")
            self.results[first_tag] = await self._scrape_tag(
                session, first_tag, solve_cf=True
            )

            # Scrape remaining tags concurrently (in batches)
            remaining = self.tags[1:]
            for i in range(0, len(remaining), _MAX_CONCURRENT_TAGS):
                batch = remaining[i : i + _MAX_CONCURRENT_TAGS]
                tasks = []
                for t in batch:
                    print(f"    --- Scraping Udemy (v2): {t} ---")
                    tasks.append(self._scrape_tag(session, t))

                batch_results = await asyncio.gather(*tasks)
                for t, res in zip(batch, batch_results):
                    self.results[t] = res

    async def _scrape_tag(self, session, tag, solve_cf=False):
        """Scrape Udemy courses for a single tag — all data extracted from the search page."""
        encoded_query = urllib.parse.quote_plus(tag)
        search_url = f"https://www.udemy.com/courses/search/?q={encoded_query}"

        print(f"    [Udemy/v2] Searching for: '{tag}'")

        try:
            page = await session.fetch(
                search_url,
                network_idle=True,
                solve_cloudflare=solve_cf,
            )
        except Exception as e:
            print(f"    [Udemy/v2] Navigation failed for '{tag}': {str(e)[:100]}")
            self.blocked_tags.append(tag)
            return []

        # Detect Cloudflare block
        page_title = (page.css("title::text").get() or "").lower()
        if any(
            sig in page_title
            for sig in (
                "just a moment",
                "attention required",
                "cloudflare",
                "please wait",
            )
        ):
            print(
                f"    [Udemy/v2] Blocked for '{tag}' — Cloudflare still active after bypass"
            )
            self.blocked_tags.append(tag)
            return []

        # Find card containers (each <section> is a full course card)
        cards = page.css(
            "section[class*='vertical-card'], div[class*='vertical-card--primary']"
        )
        if not cards:
            # Fallback: try extracting via the old header-link approach
            cards = page.css("div[class*='vertical-card-module--primary']")

        if not cards:
            print(f"    [Udemy/v2] No courses found for '{tag}'")
            return []

        tag_results = []
        for card in cards[: self.limit]:
            course = self._extract_from_card(card, tag)
            if course:
                tag_results.append(course)

        print(f"    [Udemy/v2] Extracted {len(tag_results)} courses for '{tag}'")
        return tag_results

    # ── Search Card Extraction (no course page visit needed) ──

    def _extract_from_card(self, card, tag):
        """Extract all course metadata directly from a search result card."""

        # Title + Link
        link_el = card.css("h3[class*='card-title'] a, h2[class*='card-title'] a").first
        if not link_el:
            return None

        title_div = link_el.css("div").first
        title = title_div.text.strip() if title_div else link_el.text.strip()
        href = link_el.attrib.get("href", "")
        url = href if href.startswith("http") else f"https://www.udemy.com{href}"

        # Instructor
        instructor_el = card.css(
            "span[data-purpose='safely-set-inner-html:course-card:visible-instructors']"
        ).first
        instructor = instructor_el.text.strip() if instructor_el else "N/A"

        # Rating
        rating_el = card.css("span[data-purpose='rating-number']").first
        rating = rating_el.text.strip() if rating_el else "0.0"

        # Price
        price = "N/A"
        price_el = card.css("[data-purpose='course-price-text'] span span").first
        if price_el:
            raw = price_el.text.strip()
            price = (
                raw.replace("Current price", "").replace("Original Price", "").strip()
                or "N/A"
            )

        # Image
        img_el = card.css("img[class*='card-media-image']").first
        if not img_el:
            img_el = card.css("img").first
        image_url = img_el.attrib.get("src", "") if img_el else ""

        # Extra metadata from tag list (hours, lectures, level)
        meta_tags = card.css("ul[class*='tag-list'] li div[class*='tag--']")
        hours = ""
        lectures = ""
        for mt in meta_tags or []:
            text = mt.text.strip().lower()
            if "total hour" in text:
                hours = mt.text.strip()
            elif "lecture" in text:
                lectures = mt.text.strip()

        description = " | ".join(filter(None, [hours, lectures]))
        if not description:
            description = "N/A"

        # Parse real lecture count for accurate scoring
        lecture_count = 0
        if lectures:
            m = _re.search(r"(\d+)", lectures)
            if m:
                lecture_count = int(m.group(1))

        course_data = {
            "contentType": "Course",
            "title": title,
            "instructor": instructor,
            "rating": rating,
            "price": price,
            "description": description,
            "url": url,
            "imageUrl": image_url,
            "platform": "Udemy",
            "hours": hours,
            "lectures": lectures,
            "lectureCount": lecture_count,
            "lecture_count": lecture_count,
        }

        course_data["score"] = calculate_udemy_score(course_data, tag)
        return course_data

    # ── Utility ──

    def save_to_json(self, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4, ensure_ascii=False)
        print(f"✔ Data saved to {filename}")
