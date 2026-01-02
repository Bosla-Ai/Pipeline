import asyncio
import re
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

async def fetch_coursera(sio, socket_id, tags, user_level, language='en', max_results=5):
    if not tags: return {}
    
    print(f"⏳ Starting Coursera Scraper for tags: {tags}...")
    final_roadmap = await asyncio.to_thread(
        scrape_coursera_sync, sio, socket_id, tags, user_level, language, max_results
    )
    
    return final_roadmap

def scrape_coursera_sync(sio, socket_id, tags, user_level, language, max_results):
    final_roadmap = {}
    driver = None
    lang_param = "Arabic" if language == 'ar' else "English"

    try:
        options = uc.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--blink-settings=imagesEnabled=false')
        
        driver = uc.Chrome(options=options)

        for tag in tags:
            print(f"\n--- Scraping Coursera: {tag} ({lang_param}) ---")
            url = f"https://www.coursera.org/search?query={tag}&language={lang_param}"
            print(f"    🌍 Visiting: {url}")
            driver.get(url)

            candidates = []
            seen_urls = set()

            try:
                # Wait for any links to appear
                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.TAG_NAME, "a"))
                )
                
                all_links = driver.find_elements(By.TAG_NAME, "a")
                print(f"    🔎 Scanning {len(all_links)} total links on page...")

                count = 0
                for link in all_links:
                    if count >= max_results + 5: break
                    
                    try:
                        href = link.get_attribute('href')
                        if not href: continue

                        if "/learn/" not in href and "/projects/" not in href:
                            continue
                        
                        if href in seen_urls: continue

                        title = ""
                        try:
                            title = link.find_element(By.XPATH, ".//h2 | .//h3").text.strip()
                        except:
                            title = link.get_attribute("aria-label") or link.text.split('\n')[0].strip()

                        if not title:
                            continue
                            
                        has_arabic_char = bool(re.search(r'[\u0600-\u06FF]', title))

                        data = {
                            "contentType": "Course",
                            "contentId": href,
                            "url": href,
                            "title": title,
                            "description": "Coursera Content",
                            "imageUrl": "",
                            "score": 50,
                            "is_native_arabic": has_arabic_char
                        }
                        
                        candidates.append(data)
                        seen_urls.add(href)
                        count += 1
                        
                    except Exception as inner_e:
                        continue

            except Exception as e:
                print(f"    ❌ Scraper Error: {e}")

            if candidates:
                if language == 'ar':
                    candidates.sort(key=lambda x: x['is_native_arabic'], reverse=True)
                
                winner = candidates[0]
                print(f"    🏆 Selected: {winner['title']}")
                final_roadmap[tag] = winner
            else:
                print(f"    ❌ No valid courses found for {tag}")
                final_roadmap[tag] = None

    except Exception as e:
        print(f"    ❌ Critical Scraper Error: {e}")
    
    finally:
        if driver:
            try: driver.quit()
            except: pass
            
    return final_roadmap