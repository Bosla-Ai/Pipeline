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

class UdemyFetcher:

    def __init__(self, query, limit=5, headless=False):
        self.query = query
        self.limit = limit
        self.headless = headless
        self.results = []

    def _random_sleep(self, min_time=2, max_time=5):
        time.sleep(random.uniform(min_time, max_time))

    def scrape(self):
        print(f"🔧 Headless mode: {self.headless}")
        
        xvfb_process = None
        original_display = os.environ.get('DISPLAY')
        
        try:
            if self.headless:
                # Find a free display number
                display_num = random.randint(99, 999)
                new_display = f":{display_num}"
                
                # Start Xvfb
                xvfb_process = subprocess.Popen(
                    ['Xvfb', new_display, '-screen', '0', '1920x1080x24', '+extension', 'GLX'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid
                )
                time.sleep(1)
                
                # Set display for this process and all children
                os.environ['DISPLAY'] = new_display
                print(f"🖥️  Virtual display started on {new_display}")
            
            self._run_scraper()
            
        finally:
            # Cleanup
            if xvfb_process:
                os.environ['DISPLAY'] = original_display or ':0'
                os.killpg(os.getpgid(xvfb_process.pid), signal.SIGTERM)
                print("🖥️  Virtual display stopped")

    def _run_scraper(self):
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
        browser = uc.Chrome(options=options)

        try:
            search_url = f"https://www.udemy.com/courses/search/?q={self.query}"
            print(f"🔍 Searching for: '{self.query}'")
            browser.get(search_url)

            self._random_sleep(3, 5)
            WebDriverWait(browser, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h3[class*='card-title'], h2[class*='card-title']"))
            )

            soup = BeautifulSoup(browser.page_source, "lxml")
            course_headers = soup.select("h3[class*='card-title'] a, h2[class*='card-title'] a")
            
            target_links = []
            for header in course_headers[:self.limit]:
                href = header.get("href")
                full_link = href if href.startswith("http") else "https://www.udemy.com" + href
                target_links.append(full_link)

            print(f"✔ Found {len(target_links)} courses. Extracting details...")

            for index, link in enumerate(target_links):
                print(f"   [{index + 1}/{len(target_links)}] Visiting: {link}")
                try:
                    browser.get(link)
                    WebDriverWait(browser, 15).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
                    self._random_sleep(2, 4)
                    
                    page_soup = BeautifulSoup(browser.page_source, "lxml")
                    course_data = self._extract_course_details(page_soup, link)
                    self.results.append(course_data)
                except Exception as e:
                    print(f"   ❌ Error: {e}")

        except Exception as e:
            print(f"❌ Critical Error: {e}")
        
        finally:
            print("🛑 Closing Browser...")
            browser.quit()

    def _extract_course_details(self, soup, link):
        title_tag = soup.select_one("h1[data-purpose='lead-title']")
        if not title_tag: title_tag = soup.find("h1")
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
        
        desc_tag = soup.select_one("div[data-purpose='safely-set-inner-html:description:description']")
        description = desc_tag.text.strip()[:500] + "..." if desc_tag else "N/A"

        return {
            "title": title,
            "instructor": instructor_text,
            "rating": rating_text,
            "price": price_text,
            "description": description,
            "url": link
        }

    def save_to_json(self, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4, ensure_ascii=False)
        print(f"✔ Data saved to {filename}")

