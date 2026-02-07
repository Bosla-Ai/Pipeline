import asyncio
import re
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.utils.cache import cache, generate_cache_key

import src.socket_server as socket_server


async def fetch_coursera(sio, tags, language="en", max_results=5, driver=None):
    if not tags:
        return {}

    from src.utils.helpers import classify_via_frontend

    await cache.connect()

    final_roadmap = {}
    tags_to_fetch = []

    for tag in tags:
        cache_key = generate_cache_key("coursera", tag, language)
        cached_result = await cache.get(cache_key)
        if cached_result:
            print(f"    ✅ [Cache Hit] Coursera: {tag} ({language})")
            final_roadmap[tag] = cached_result
        else:
            tags_to_fetch.append(tag)

    if not tags_to_fetch:
        return final_roadmap

    print(f"⏳ Starting Coursera Scraper for tags: {tags_to_fetch}...")
    candidates_map = await asyncio.to_thread(
        scrape_coursera_sync, sio, tags_to_fetch, language, max_results, driver
    )

    for tag, candidates in candidates_map.items():
        if not candidates:
            final_roadmap[tag] = None
            continue

        print(
            f"    🤖 AI Analyzing {len(candidates)} Coursera Candidates for '{tag}'..."
        )

        # Apply AI Classification
        socket_id = socket_server.active_socket_id
        valid_items = await classify_via_frontend(sio, socket_id, tag, candidates)

        if valid_items:
            # Sort by Native Arabic first if needed
            if language == "ar":
                valid_items.sort(key=lambda x: x["is_native_arabic"], reverse=True)

            winner = valid_items[0]
            print(f"    🏆 [AI] Coursera Winner: {winner['title'][:50]}...")
            final_roadmap[tag] = winner
            cache_key = generate_cache_key("coursera", tag, language)
            await cache.set(cache_key, winner)
        else:
            print(
                f"    ⚠️ AI rejected all Coursera items (or frontend error). Using Safety Net."
            )
            # Fallback to the first candidate (which is usually the most relevant from search)
            winner = candidates[0]
            final_roadmap[tag] = winner
            # Ensure native arabic sort applies to fallback too if needed
            if language == "ar":
                candidates.sort(key=lambda x: x["is_native_arabic"], reverse=True)
                final_roadmap[tag] = candidates[0]
            cache_key = generate_cache_key("coursera", tag, language)
            await cache.set(cache_key, final_roadmap[tag])

    return final_roadmap


def scrape_coursera_sync(sio, tags, language, max_results, existing_driver=None):
    candidates_map = {}
    driver = existing_driver
    local_driver = False
    lang_param = "Arabic" if language == "ar" else "English"

    try:
        if not driver:
            local_driver = True
            options = uc.ChromeOptions()
            # options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--blink-settings=imagesEnabled=false")
            driver = uc.Chrome(options=options, version_main=144)
        else:
            print("    ♻️ Reusing Global Coursera Driver")

        for tag in tags:
            print(f"\n--- Scraping Coursera: {tag} ({lang_param}) ---")
            import urllib.parse

            encoded_tag = urllib.parse.quote_plus(tag)
            url = f"https://www.coursera.org/search?query={encoded_tag}&language={lang_param}"
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
                # print(f"    🔎 Scanning {len(all_links)} total links on page...")
                print(
                    f"    🔎 [Coursera] Scanning {len(all_links)} links for '{tag}'..."
                )

                count = 0
                for link in all_links:
                    if count >= max_results + 5:
                        break

                    try:
                        href = link.get_attribute("href")
                        if not href:
                            continue

                        # Expanded valid URL patterns
                        if (
                            "/learn/" not in href
                            and "/projects/" not in href
                            and "/specializations/" not in href
                            and "/professional-certificates/" not in href
                        ):
                            continue

                        if href in seen_urls:
                            continue

                        title = ""
                        try:
                            title = link.find_element(
                                By.XPATH, ".//h2 | .//h3"
                            ).text.strip()
                        except:
                            title = (
                                link.get_attribute("aria-label")
                                or link.text.split("\n")[0].strip()
                            )

                        if not title:
                            continue

                        has_arabic_char = bool(re.search(r"[\u0600-\u06FF]", title))

                        # Default metadata for scoring
                        data = {
                            "contentType": "Course",
                            "contentId": href,
                            "url": href,
                            "title": title,
                            "description": "Coursera Content",
                            "imageUrl": "",
                            "videoCount": 40,
                            "subscriberCount": 500000,
                            "publishedAt": "2024-01-01T00:00:00Z",
                            "is_native_arabic": has_arabic_char,
                        }

                        from src.utils.scoring import calculate_playlist_score

                        data["score"] = calculate_playlist_score(data)

                        candidates.append(data)
                        seen_urls.add(href)
                        count += 1
                        # print(f"    ✔ Found: {title[:30]}...")

                    except Exception as inner_e:
                        continue

                print(f"    ✔ [Coursera] Found {len(candidates)} valid candidates.")

            except Exception as e:
                print(f"    ❌ [Coursera] Error: {e}")

            if language == "ar" and candidates:
                candidates.sort(key=lambda x: x["is_native_arabic"], reverse=True)

            if candidates:
                candidates_map[tag] = candidates
            else:
                print(f"    ⚠️ [Coursera] No results for '{tag}'")
                candidates_map[tag] = []

    except Exception as e:
        print(f"    ❌ [Coursera] Critical Error: {e}")

    finally:
        if driver and local_driver:
            if driver:
                try:
                    import time

                    time.sleep(2)
                    driver.quit()
                    time.sleep(2)  # Extra time for OS to release file handle
                except:
                    pass

    return candidates_map
