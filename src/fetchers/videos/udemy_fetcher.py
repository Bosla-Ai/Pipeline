import time
import json
import random
import subprocess
import os
import signal
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from src.utils.scoring import calculate_playlist_score


class UdemyFetcher:

    def __init__(self, tags, limit=5, headless=False, driver=None):
        self.tags = tags
        self.limit = limit
        self.headless = headless
        self.driver = driver
        self.results = {}

    def _random_sleep(self, min_time=0.5, max_time=1.5):
        time.sleep(random.uniform(min_time, max_time))

    def _log_diagnostic(self, browser):
        """Log diagnostic info when errors occur to help debug block pages."""
        try:
            print(f"    🔍 [Diagnostic] URL: {browser.current_url}")
            print(f"    🔍 [Diagnostic] Title: {browser.title}")
        except:
            print("    🔍 [Diagnostic] Could not retrieve browser state")

    def scrape(self):
        # print(f"🔧 Headless mode: {self.headless}")

        # If external driver provided, skip local Xvfb/Driver setup
        if self.driver:
            print("    ♻️ Reusing Global Udemy Driver")
            try:
                self._scrape_with_driver(self.driver)
            except Exception as e:
                print(f"❌ Error with global driver: {e}")
            return

        # --- LOCAL DRIVER LOGIC (Fallback) ---
        xvfb_process = None
        original_display = os.environ.get("DISPLAY")

        try:
            if self.headless:
                # Find a free display number
                display_num = random.randint(99, 999)
                new_display = f":{display_num}"

                # Start Xvfb
                xvfb_process = subprocess.Popen(
                    [
                        "Xvfb",
                        new_display,
                        "-screen",
                        "0",
                        "1920x1080x24",
                        "+extension",
                        "GLX",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid,
                )
                time.sleep(1)

                # Set display for this process and all children
                os.environ["DISPLAY"] = new_display
                print(f"🖥️  Virtual display started on {new_display}")

            self._run_local_scraper()

        finally:
            # Cleanup
            if xvfb_process:
                os.environ["DISPLAY"] = original_display or ":0"
                os.killpg(os.getpgid(xvfb_process.pid), signal.SIGTERM)
                print("🖥️  Virtual display stopped")

    def _scrape_with_driver(self, browser):
        # Health check and reset driver state before Udemy scraping
        try:
            # Navigate to a neutral page first to reset state
            browser.get("about:blank")
            time.sleep(0.5)
            
            # Clear all browser state from previous scraping (Coursera)
            browser.delete_all_cookies()
            try:
                browser.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
            except:
                pass  # Ignore if script fails on about:blank
            
            # Verify driver is responsive
            _ = browser.current_url
            print("    ✅ [Udemy] Driver health check passed, state cleared")
        except Exception as health_error:
            print(f"⚠️ [Udemy] Driver health check failed: {health_error}")
            raise RuntimeError("Udemy driver unhealthy - cannot proceed")
        
        # Re-using the core logic with an existing browser instance
        self._core_scraping_logic(browser)

    def _run_local_scraper(self):
        options = uc.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--mute-audio")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        # Force X11 instead of Wayland so Xvfb virtual display works
        options.add_argument("--ozone-platform=x11")

        print("🚀 Initializing Browser...")
        browser = uc.Chrome(options=options, version_main=144)

        try:
            self._core_scraping_logic(browser)
        finally:
            print("🛑 Closing Browser...")
            try:
                time.sleep(2)
                browser.quit()
                time.sleep(2)
            except:
                pass

    def _core_scraping_logic(self, browser):
        try:
            for tag in self.tags:
                print(f"--- Scraping Udemy: {tag} ---")
                tag_results = []
                try:
                    import urllib.parse

                    encoded_query = urllib.parse.quote_plus(tag)
                    search_url = (
                        f"https://www.udemy.com/courses/search/?q={encoded_query}"
                    )
                    print(f"🔍 Searching for: '{tag}' (Encoded: {encoded_query})")
                    
                    try:
                        browser.get(search_url)
                    except WebDriverException as nav_err:
                        print(f"❌ [Udemy] Navigation failed (driver crash): {str(nav_err)[:100]}")
                        self._log_diagnostic(browser)
                        self.results[tag] = []
                        continue

                    self._random_sleep(1.5, 3)
                    
                    try:
                        WebDriverWait(browser, 20).until(
                            EC.presence_of_element_located(
                                (
                                    By.CSS_SELECTOR,
                                    "h3[class*='card-title'], h2[class*='card-title']",
                                )
                            )
                        )
                    except TimeoutException:
                        print(f"⚠️ [Udemy] No courses found for '{tag}' (possible block or empty results)")
                        self._log_diagnostic(browser)
                        self.results[tag] = []
                        continue
                    except WebDriverException as wait_err:
                        print(f"❌ [Udemy] Driver crash during wait: {str(wait_err)[:100]}")
                        self._log_diagnostic(browser)
                        self.results[tag] = []
                        continue

                    soup = BeautifulSoup(browser.page_source, "lxml")
                    course_headers = soup.select(
                        "h3[class*='card-title'] a, h2[class*='card-title'] a"
                    )

                    target_links = []
                    for header in course_headers[: self.limit]:
                        href = header.get("href")
                        full_link = (
                            href
                            if href.startswith("http")
                            else "https://www.udemy.com" + href
                        )
                        target_links.append(full_link)

                    print(
                        f"    🔎 [Udemy] Found {len(target_links)} raw results for '{tag}'"
                    )
                    # print(f"✔ Found {len(target_links)} courses for '{tag}'")

                    for index, link in enumerate(target_links):
                        # print(f"   [{index + 1}/{len(target_links)}] Visiting: {link}")
                        try:
                            browser.get(link)
                            WebDriverWait(browser, 15).until(
                                EC.presence_of_element_located((By.TAG_NAME, "h1"))
                            )
                            self._random_sleep(0.5, 1.0)

                            page_soup = BeautifulSoup(browser.page_source, "lxml")
                            course_data = self._extract_course_details(page_soup, link)
                            tag_results.append(course_data)
                        except Exception as e:
                            # print(f"   ❌ Error visiting {link}: {e}")
                            pass

                    print(
                        f"    ✔ [Udemy] Successfully extracted {len(tag_results)} courses."
                    )
                    self.results[tag] = tag_results

                except Exception as e_tag:
                    print(f"❌ Error scraping tag '{tag}': {e_tag}")
                    self.results[tag] = []

        except Exception as e:
            print(f"❌ Critical Scraper Error: {e}")

    def _extract_course_details(self, soup, link):
        title_tag = soup.select_one("h1[data-purpose='lead-title']")
        if not title_tag:
            title_tag = soup.find("h1")
        title = title_tag.text.strip() if title_tag else "N/A"

        instructor = soup.select_one("[data-purpose='instructor-name-top']")
        instructor_text = instructor.text.strip() if instructor else "N/A"

        rating = soup.select_one("[data-purpose='rating-number']")
        rating_text = rating.text.strip() if rating else "0.0"

        # Extract price
        price_tag = soup.select_one("[data-purpose='course-price-text'] span span")
        if not price_tag:
            price_tag = soup.select_one("[data-purpose='course-price-text']")
        if not price_tag:
            price_tag = soup.select_one("div[class*='price-text'] span span")
        price_text = price_tag.text.strip() if price_tag else "N/A"

        desc_tag = soup.select_one(
            "div[data-purpose='safely-set-inner-html:description:description']"
        )
        description = desc_tag.text.strip()[:500] + "..." if desc_tag else "N/A"

        course_data = {
            "contentType": "Course",
            "title": title,
            "instructor": instructor_text,
            "rating": rating_text,
            "price": price_text,
            "description": description,
            "url": link,
            # Defaults for Scoring
            "videoCount": 50,  # Assume full course
            "subscriberCount": 100000,  # Udemy instructors usually have high reach
            "publishedAt": "2024-01-01T00:00:00Z",  # Assume fresh
        }

        course_data["score"] = calculate_playlist_score(course_data)

        return course_data

    def save_to_json(self, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4, ensure_ascii=False)
        print(f"✔ Data saved to {filename}")
