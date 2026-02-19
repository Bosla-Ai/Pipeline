"""
Udemy course scraper with dual-strategy Cloudflare Turnstile bypass.

Primary:  nodriver  (CDP-based, no WebDriver protocol - best Turnstile evasion)
Fallback: undetected_chromedriver (if nodriver unavailable or crashes)
"""

import asyncio
import json
import os
import random
import time
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup

from src.fetchers.scraping_utils import (
    STEALTH_JS,
    is_cloudflare_challenge,
    load_cookies,
    save_cookies,
)
from src.utils.scoring import calculate_playlist_score


class UdemyFetcher:
    """Udemy course scraper using nodriver for Cloudflare Turnstile bypass."""

    def __init__(self, tags, limit=5, headless=True, driver=None):
        self.tags = tags
        self.limit = limit
        self.headless = headless
        # Legacy driver kept for fallback compatibility (undetected_chromedriver)
        self._legacy_driver = driver
        self.results = {}
        self.blocked_tags = []

    # Public API (sync - backward-compatible)

    def scrape(self):
        """
        Sync entry point - internally runs the async nodriver scraper.
        Uses Xvfb virtual display for non-headless mode (critical for Turnstile bypass).
        Falls back to undetected_chromedriver if nodriver is unavailable.
        """
        xvfb_proc = None
        original_display = os.environ.get("DISPLAY")
        try:
            # Start Xvfb virtual display for non-headless browser
            # Non-headless mode is critical — Turnstile detects headless browsers
            xvfb_proc = self._start_xvfb()
            asyncio.run(self._async_scrape())
        except ImportError as e:
            print(f"    [Udemy] nodriver not installed ({e}) - using legacy driver")
            self._scrape_legacy()
        except Exception as e:
            print(f"    [Udemy] nodriver failed: {e}")
            if self._legacy_driver:
                print("    [Udemy] Falling back to legacy undetected_chromedriver...")
                self._scrape_legacy()
            else:
                print("    [Udemy] No fallback driver available")
        finally:
            self._stop_xvfb(xvfb_proc, original_display)

    def _start_xvfb(self):
        """Start Xvfb virtual display so Chrome runs non-headless (invisible)."""
        import subprocess
        import shutil

        if not shutil.which("Xvfb"):
            print("    [Udemy] Xvfb not found - falling back to headless mode")
            return None

        # Pick a random display number to avoid conflicts
        display_num = random.randint(99, 199)
        display = f":{display_num}"

        try:
            proc = subprocess.Popen(
                ["Xvfb", display, "-screen", "0", "1920x1080x24", "-ac"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)  # Let Xvfb start
            if proc.poll() is not None:
                print(f"    [Udemy] Xvfb failed to start on {display}")
                return None

            os.environ["DISPLAY"] = display
            self.headless = False  # Force non-headless since we have a virtual display
            print(f"    [Udemy] Xvfb started on {display}")
            return proc
        except Exception as e:
            print(f"    [Udemy] Xvfb error: {e}")
            return None

    def _stop_xvfb(self, proc, original_display):
        """Stop Xvfb and restore DISPLAY env var."""
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            print("    [Udemy] Xvfb stopped")

        # Restore original DISPLAY
        if original_display is not None:
            os.environ["DISPLAY"] = original_display
        elif "DISPLAY" in os.environ:
            del os.environ["DISPLAY"]

    # nodriver implementation (async)

    async def _async_scrape(self):
        """Core async scraper using nodriver."""
        import nodriver as nd

        browser = None
        try:
            # Minimal, non-suspicious browser args
            # Avoid bot-like flags (--disable-gpu, --no-sandbox etc. are fingerprint signals)
            browser_args = [
                "--window-size=1920,1080",
                "--mute-audio",
            ]
            # Only add sandbox/gpu flags when running headless (no Xvfb)
            if self.headless:
                browser_args.extend(
                    [
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ]
                )

            mode_label = "headless" if self.headless else "non-headless (Xvfb)"
            print(f"    [Udemy] Launching nodriver browser ({mode_label})...")
            browser = await nd.start(
                headless=self.headless,
                browser_args=browser_args,
                lang="en-US",
            )

            # Get the initial tab
            tab = browser.main_tab

            # Inject stealth scripts before any navigation
            await self._inject_stealth(tab)

            # Restore cookies from previous session
            await self._restore_cookies(tab)

            # Warm up session by visiting homepage
            session_ready = await self._warm_up(tab)
            if not session_ready:
                print("    [Udemy] Warm-up failed - will attempt searches anyway")

            # Scrape each tag
            for tag in self.tags:
                print(f"    --- Scraping Udemy: {tag} ---")
                tag_results = await self._scrape_tag(tab, tag)
                self.results[tag] = tag_results
                # Polite delay between tags to reduce detection
                await asyncio.sleep(random.uniform(2.0, 4.0))

            # Persist cookies for next run
            await self._persist_cookies(tab)

        except Exception as e:
            print(f"    [Udemy] Critical nodriver error: {e}")
            raise  # Re-raise to trigger fallback in scrape()
        finally:
            if browser:
                try:
                    browser.stop()
                    print("    [Udemy] Browser closed")
                except Exception:
                    pass

    async def _inject_stealth(self, tab):
        """Inject CDP-level stealth to mask automation signals."""
        try:
            await tab.evaluate(STEALTH_JS)
        except Exception as e:
            print(f"    [Udemy] Stealth injection warning: {e}")

    async def _restore_cookies(self, tab):
        """Restore saved cookies from a previous session via CDP."""
        cookies = load_cookies("udemy")
        if not cookies:
            return
        try:
            import nodriver.cdp.network as network

            restored = 0
            for cookie in cookies:
                try:
                    await tab.send(
                        network.set_cookie(
                            name=cookie["name"],
                            value=cookie["value"],
                            domain=cookie.get("domain", ".udemy.com"),
                            path=cookie.get("path", "/"),
                            secure=cookie.get("secure", True),
                            http_only=cookie.get("httpOnly", False),
                        )
                    )
                    restored += 1
                except Exception:
                    pass
            if restored:
                print(f"    [Udemy] Restored {restored}/{len(cookies)} cookies")
        except Exception as e:
            print(f"    [Udemy] Cookie restore failed: {e}")

    async def _persist_cookies(self, tab):
        """Save current browser cookies to disk for session persistence."""
        try:
            import nodriver.cdp.network as network

            all_cookies = await tab.send(network.get_all_cookies())
            udemy_cookies = []
            for c in all_cookies:
                domain = getattr(c, "domain", "") or ""
                if "udemy" in domain:
                    udemy_cookies.append(
                        {
                            "name": c.name,
                            "value": c.value,
                            "domain": domain,
                            "path": getattr(c, "path", "/"),
                            "secure": getattr(c, "secure", True),
                            "httpOnly": getattr(c, "http_only", False),
                        }
                    )
            if udemy_cookies:
                save_cookies("udemy", udemy_cookies)
        except Exception as e:
            print(f"    [Udemy] Cookie persist failed: {e}")

    # Turnstile Detection and Handling

    async def _get_page_title(self, tab) -> str:
        """Safely get the current page title."""
        try:
            return (await tab.evaluate("document.title")) or ""
        except Exception:
            return ""

    async def _get_page_html(self, tab) -> str:
        """Safely get the current page HTML."""
        try:
            return await tab.get_content()
        except Exception:
            return ""

    async def _is_blocked(self, tab) -> bool:
        """Check if current page is a Cloudflare/Turnstile challenge."""
        title = await self._get_page_title(tab)
        html = await self._get_page_html(tab)
        return is_cloudflare_challenge(html, title)

    async def _wait_for_turnstile(self, tab, timeout=30) -> bool:
        """
        Wait for Turnstile to auto-resolve (non-interactive mode).
        Returns True if the challenge resolved; False if still blocked.
        """
        print(f"    [Udemy] Turnstile detected - waiting up to {timeout}s...")
        deadline = time.time() + timeout

        while time.time() < deadline:
            if not await self._is_blocked(tab):
                print("    [Udemy] Turnstile resolved!")
                return True
            await asyncio.sleep(1.5)

        # Last resort: try clicking the Turnstile widget
        try:
            html = await self._get_page_html(tab)
            if "challenges.cloudflare.com" in html:
                print("    [Udemy] Attempting to click Turnstile widget...")
                turnstile = await tab.select('iframe[src*="challenges.cloudflare.com"]')
                if turnstile:
                    await turnstile.click()
                    await asyncio.sleep(5)
                    if not await self._is_blocked(tab):
                        print("    [Udemy] Turnstile resolved after click!")
                        return True
        except Exception:
            pass

        return False

    # Warm-up and Human Simulation

    async def _warm_up(self, tab) -> bool:
        """Navigate to Udemy homepage to establish a trusted session."""
        try:
            print("    [Udemy] Warming up - navigating to homepage...")
            await tab.get("https://www.udemy.com/")
            await asyncio.sleep(random.uniform(3, 5))

            # Re-inject stealth after navigation (page context resets)
            await self._inject_stealth(tab)

            if await self._is_blocked(tab):
                if not await self._wait_for_turnstile(tab, timeout=30):
                    title = await self._get_page_title(tab)
                    print(f"    [Udemy] Still blocked - Title: {title}")
                    return False

            # Simulate realistic human behavior
            await self._simulate_human(tab)

            print("    [Udemy] Homepage loaded - session is warm")
            return True
        except Exception as e:
            print(f"    [Udemy] Warm-up failed: {e}")
            return False

    async def _simulate_human(self, tab):
        """Simulate realistic human browsing to build trust with Cloudflare."""
        try:
            # Scroll down in natural increments
            for _ in range(random.randint(2, 4)):
                scroll_amount = random.randint(200, 500)
                await tab.evaluate(f"window.scrollBy(0, {scroll_amount})")
                await asyncio.sleep(random.uniform(0.5, 1.2))

            # Pause at bottom like reading
            await asyncio.sleep(random.uniform(0.5, 1.0))

            # Scroll back up
            await tab.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(random.uniform(0.3, 0.8))
        except Exception:
            pass

    # Core Scraping Logic

    async def _scrape_tag(self, tab, tag):
        """Scrape Udemy courses for a single tag/topic."""
        tag_results = []
        encoded_query = urllib.parse.quote_plus(tag)
        search_url = f"https://www.udemy.com/courses/search/?q={encoded_query}"

        print(f"    [Udemy] Searching for: '{tag}'")

        try:
            await tab.get(search_url)
        except Exception as nav_err:
            print(f"    [Udemy] Navigation failed: {str(nav_err)[:100]}")
            return []

        await asyncio.sleep(random.uniform(2, 4))

        # Re-inject stealth after navigation
        await self._inject_stealth(tab)

        # Check for Turnstile on search results
        if await self._is_blocked(tab):
            if not await self._wait_for_turnstile(tab, timeout=20):
                print(f"    [Udemy] Blocked for '{tag}' - skipping")
                self.blocked_tags.append(tag)
                return []

        # Wait for course cards with polling retry
        course_headers = []
        for attempt in range(4):
            html = await self._get_page_html(tab)
            soup = BeautifulSoup(html, "lxml")
            course_headers = soup.select(
                "h3[class*='card-title'] a, h2[class*='card-title'] a"
            )
            if course_headers:
                break
            await asyncio.sleep(2)

        if not course_headers:
            print(f"    [Udemy] No courses found for '{tag}'")
            return []

        # Extract course links
        target_links = []
        for header in course_headers[: self.limit]:
            href = header.get("href")
            if href:
                full_link = (
                    href if href.startswith("http") else f"https://www.udemy.com{href}"
                )
                target_links.append(full_link)

        print(f"    [Udemy] Found {len(target_links)} results for '{tag}'")

        # Visit each course page to extract details
        for index, link in enumerate(target_links):
            try:
                await tab.get(link)
                await asyncio.sleep(random.uniform(1, 2))

                # Re-inject stealth after each navigation
                await self._inject_stealth(tab)

                # Wait for h1 title with polling
                for _ in range(6):
                    html = await self._get_page_html(tab)
                    if "<h1" in html.lower():
                        break
                    await asyncio.sleep(1)

                # Extra wait for price/buy-box to render (React lazy-loads it)
                for _ in range(4):
                    html = await self._get_page_html(tab)
                    if "course-price-text" in html or "price-container" in html:
                        break
                    await asyncio.sleep(1)

                html = await self._get_page_html(tab)
                page_soup = BeautifulSoup(html, "lxml")
                course_data = self._extract_course_details(page_soup, link)
                tag_results.append(course_data)
            except Exception:
                pass

        print(f"    [Udemy] Extracted {len(tag_results)} courses for '{tag}'")
        return tag_results

    # Course Detail Extraction

    def _extract_course_details(self, soup, link):
        """Extract course metadata from a Udemy course page."""
        title_tag = soup.select_one("h1[data-purpose='lead-title']")
        if not title_tag:
            title_tag = soup.find("h1")
        title = title_tag.text.strip() if title_tag else "N/A"

        # Instructor — try multiple selectors (Udemy updates its markup frequently)
        instructor_text = "N/A"
        for sel in [
            "[data-purpose='instructor-name-top']",
            "a[class*='instructor-link']",
            "a[class*='instructor']",
            "div[class*='instructor'] a",
            "a[href*='/user/']",
        ]:
            matches = soup.select(sel)
            if matches:
                names = [m.text.strip() for m in matches if m.text.strip()]
                if names:
                    instructor_text = ", ".join(
                        dict.fromkeys(names)
                    )  # dedupe, preserve order
                    break

        rating = soup.select_one("[data-purpose='rating-number']")
        rating_text = rating.text.strip() if rating else "0.0"

        # Extract price — multiple fallback selectors
        price_text = "N/A"
        for sel in [
            "[data-purpose='course-price-text'] span span",
            "div[class*='discount-price'] span:last-child",
            "[data-purpose='course-price-text']",
            "div[class*='price-text'] span span",
            "[class*='price-container'] [class*='discount-price']",
        ]:
            tag = soup.select_one(sel)
            if tag:
                raw = tag.text.strip()
                # Clean up "Current price" prefix that Udemy prepends
                cleaned = (
                    raw.replace("Current price", "")
                    .replace("Original Price", "")
                    .strip()
                )
                if cleaned:
                    price_text = cleaned
                    break

        desc_tag = soup.select_one(
            "div[data-purpose='safely-set-inner-html:description:description']"
        )
        description = desc_tag.text.strip()[:500] + "..." if desc_tag else "N/A"

        # Extract course image (og:image meta tag is most reliable)
        image_url = ""
        og_image = soup.select_one("meta[property='og:image']")
        if og_image and og_image.get("content"):
            image_url = og_image["content"]
        else:
            # Fallback: course intro video poster or img in intro asset
            for img_sel in [
                "img[class*='intro-asset']",
                "span[class*='intro-asset'] img",
                "img[data-purpose='introduction-asset']",
            ]:
                img_tag = soup.select_one(img_sel)
                if img_tag and img_tag.get("src"):
                    image_url = img_tag["src"]
                    break

        course_data = {
            "contentType": "Course",
            "title": title,
            "instructor": instructor_text,
            "rating": rating_text,
            "price": price_text,
            "description": description,
            "url": link,
            "imageUrl": image_url,
            "platform": "Udemy",
            # Defaults for scoring
            "videoCount": 50,
            "subscriberCount": 100000,
            "publishedAt": "2024-01-01T00:00:00Z",
        }

        course_data["score"] = calculate_playlist_score(course_data)
        return course_data

    # Legacy fallback (undetected_chromedriver)

    def _scrape_legacy(self):
        """Fallback scraper using undetected_chromedriver."""
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import TimeoutException, WebDriverException

        browser = self._legacy_driver
        owns_browser = False

        if not browser:
            options = uc.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--mute-audio")
            options.add_argument("--disable-blink-features=AutomationControlled")
            print("    [Udemy/Legacy] Creating fallback browser...")
            browser = uc.Chrome(options=options)
            owns_browser = True
        else:
            print("    [Udemy/Legacy] Reusing provided driver")
            try:
                browser.get("about:blank")
                time.sleep(0.5)
                browser.delete_all_cookies()
            except Exception:
                pass

        try:
            self._legacy_core(browser)
        finally:
            if owns_browser:
                try:
                    browser.quit()
                except Exception:
                    pass

    def _legacy_core(self, browser):
        """Original scraping logic with undetected_chromedriver."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import TimeoutException

        # Warm up - visit homepage first
        try:
            browser.get("https://www.udemy.com/")
            time.sleep(random.uniform(4, 6))

            deadline = time.time() + 30
            while time.time() < deadline:
                title = (browser.title or "").lower()
                if not any(
                    s in title for s in ("just a moment", "cloudflare", "please wait")
                ):
                    break
                time.sleep(1)
        except Exception as e:
            print(f"    [Udemy/Legacy] Warm-up failed: {e}")

        for tag in self.tags:
            if tag in self.results:
                continue
            tag_results = []
            try:
                encoded = urllib.parse.quote_plus(tag)
                url = f"https://www.udemy.com/courses/search/?q={encoded}"
                browser.get(url)
                time.sleep(random.uniform(1.5, 3))

                card_sel = "h3[class*='card-title'], h2[class*='card-title']"
                try:
                    WebDriverWait(browser, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, card_sel))
                    )
                except TimeoutException:
                    self.blocked_tags.append(tag)
                    self.results[tag] = []
                    continue

                soup = BeautifulSoup(browser.page_source, "lxml")
                headers = soup.select(
                    "h3[class*='card-title'] a, h2[class*='card-title'] a"
                )
                links = []
                for h in headers[: self.limit]:
                    href = h.get("href")
                    if href:
                        links.append(
                            href
                            if href.startswith("http")
                            else f"https://www.udemy.com{href}"
                        )

                for link in links:
                    try:
                        browser.get(link)
                        WebDriverWait(browser, 15).until(
                            EC.presence_of_element_located((By.TAG_NAME, "h1"))
                        )
                        time.sleep(random.uniform(0.5, 1))
                        page_soup = BeautifulSoup(browser.page_source, "lxml")
                        tag_results.append(
                            self._extract_course_details(page_soup, link)
                        )
                    except Exception:
                        pass

                self.results[tag] = tag_results
                time.sleep(random.uniform(1.5, 3))
            except Exception:
                self.results[tag] = []

    # Utility

    def save_to_json(self, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4, ensure_ascii=False)
        print(f"✔ Data saved to {filename}")
