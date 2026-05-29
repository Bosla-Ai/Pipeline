import asyncio
import re
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.utils.cache import cache, generate_cache_key


async def fetch_coursera(
    sio, socket_id, tags, language="en", max_results=5, driver=None, job_id=None
):
    if not tags:
        return {}

    from src.utils.helpers import classify_via_frontend
    from src.utils.event_log import event_log
    import uuid

    await cache.connect()

    final_roadmap = {}
    tags_to_fetch = []

    for tag in tags:
        cache_key = generate_cache_key("coursera", tag, language)
        cached_result = await cache.get(cache_key)
        if cached_result:
            print(f"    [Cache Hit] Coursera: {tag} ({language})")
            event_log.log(
                "success",
                "cache",
                "cache_hit",
                job_id=job_id,
                metadata={
                    "source": "coursera",
                    "tag": tag,
                    "language": language,
                }
            )
            final_roadmap[tag] = cached_result
        else:
            event_log.log(
                "info",
                "cache",
                "cache_miss",
                job_id=job_id,
                metadata={
                    "source": "coursera",
                    "tag": tag,
                    "language": language,
                }
            )
            tags_to_fetch.append(tag)

    if not tags_to_fetch:
        return final_roadmap

    async def process_and_cache_candidates(tag, candidates):
        if not candidates:
            final_roadmap[tag] = None
            return None

        # Normalization, Deduplication, and Cheap Ranking
        from src.engine.models import Candidate, SourceName
        from src.engine.runtime import runtime_limits
        from src.ranking.dedupe import dedupe_candidates
        from src.ranking.cheap_ranker import cheap_rank

        candidate_objs = [
            Candidate.from_dict(c, SourceName.COURSERA, tag) for c in candidates
        ]
        deduped_objs = dedupe_candidates(candidate_objs)
        ranked_objs = cheap_rank(deduped_objs, tag)[
            : runtime_limits.cheap_rank_limit_per_tag
        ]

        ranked_dicts = [c.to_dict() for c in ranked_objs]

        event_log.log(
            "success",
            "job",
            "cheap_rank_completed",
            job_id=job_id,
            metadata={
                "source": "coursera",
                "tag": tag,
                "candidate_pool_size": len(candidates),
                "ranked_count": len(ranked_dicts),
            }
        )

        if not ranked_dicts:
            final_roadmap[tag] = None
            return None

        print(
            f"    [Coursera] AI Analyzing {len(ranked_dicts)} Coursera Candidates for '{tag}'..."
        )

        # Apply AI Classification using the job-scoped socket_id
        valid_items = await classify_via_frontend(sio, socket_id, tag, ranked_dicts, job_id=job_id)

        if valid_items:
            # Sort by Native Arabic first if needed
            if language == "ar":
                valid_items.sort(key=lambda x: x["is_native_arabic"], reverse=True)

            winner = valid_items[0]
            print(f"    [Coursera] [AI] Coursera Winner: {winner['title'][:50]}...")
            final_roadmap[tag] = winner
            cache_key = generate_cache_key("coursera", tag, language)
            await cache.set(cache_key, winner)
            return winner
        else:
            print(
                f"    [Coursera] AI rejected all Coursera items (or frontend error). Using Safety Net."
            )
            # Fallback to the first candidate (which is usually the most relevant from search)
            winner = ranked_dicts[0]
            if language == "ar":
                ranked_dicts.sort(key=lambda x: x["is_native_arabic"], reverse=True)
                winner = ranked_dicts[0]
            final_roadmap[tag] = winner
            cache_key = generate_cache_key("coursera", tag, language)
            await cache.set(cache_key, winner)
            return winner

    tags_to_scrape = []
    tags_to_wait = []
    locked_tokens = {}

    for tag in tags_to_fetch:
        cache_key = generate_cache_key("coursera", tag, language)
        token = str(uuid.uuid4())
        acquired = await cache.acquire_lock(cache_key, token, ttl=60)
        if acquired is True:
            locked_tokens[tag] = token
            tags_to_scrape.append(tag)
        elif acquired is None:
            # Cache unavailable/infra failure: scrape immediately
            tags_to_scrape.append(tag)
        else:
            tags_to_wait.append(tag)

    if tags_to_scrape:
        try:
            print(f"[Coursera] Starting Coursera Scraper for tags: {tags_to_scrape}...")
            candidates_map = await asyncio.to_thread(
                scrape_coursera_sync, sio, tags_to_scrape, language, max_results, driver
            )
            for tag in tags_to_scrape:
                candidates = candidates_map.get(tag, [])
                await process_and_cache_candidates(tag, candidates)
        finally:
            for tag, token in locked_tokens.items():
                cache_key = generate_cache_key("coursera", tag, language)
                await cache.release_lock(cache_key, token)

    if tags_to_wait:
        print(f"    [Cache Stampede Protection] Waiting for Coursera locks on: {tags_to_wait}...")
        for tag in tags_to_wait:
            cache_key = generate_cache_key("coursera", tag, language)
            resolved = False
            for _ in range(30):  # 15 seconds max wait
                await asyncio.sleep(0.5)
                try:
                    cached = await cache.get(cache_key)
                except Exception as ce:
                    print(f"    [Cache Wait] Error reading cached result for {tag}: {ce}")
                    cached = None
                if cached is not None:
                    print(f"    [Cache Hit via Lock] Coursera: {tag} ({language})")
                    event_log.log(
                        "success",
                        "cache",
                        "cache_hit",
                        job_id=job_id,
                        metadata={
                            "source": "coursera",
                            "tag": tag,
                            "language": language,
                            "stampede_protection": True,
                        }
                    )
                    final_roadmap[tag] = cached
                    resolved = True
                    break
            if not resolved:
                print(f"    [Cache Wait Timeout] Falling back to scrape Coursera for '{tag}' individually...")
                event_log.log(
                    "info",
                    "cache",
                    "cache_miss_fallback",
                    job_id=job_id,
                    metadata={
                        "source": "coursera",
                        "tag": tag,
                        "language": language,
                        "reason": "lock_wait_timeout",
                    }
                )
                single_map = await asyncio.to_thread(
                    scrape_coursera_sync, sio, [tag], language, max_results, driver
                )
                candidates = single_map.get(tag, [])
                await process_and_cache_candidates(tag, candidates)

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
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--js-flags=--max-old-space-size=256")
            options.add_argument("--blink-settings=imagesEnabled=false")
            driver = uc.Chrome(options=options)
        else:
            print("    [Coursera] Reusing Global Coursera Driver")

        for tag in tags:
            print(f"\n--- Scraping Coursera: {tag} ({lang_param}) ---")
            import urllib.parse

            encoded_tag = urllib.parse.quote_plus(tag)
            url = f"https://www.coursera.org/search?query={encoded_tag}&language={lang_param}"
            print(f"    [Coursera] Visiting: {url}")
            driver.get(url)

            candidates = []
            seen_urls = set()

            try:
                # Wait for any links to appear
                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.TAG_NAME, "a"))
                )

                all_links = driver.find_elements(By.TAG_NAME, "a")
                print(f"    [Coursera] Scanning {len(all_links)} links for '{tag}'...")

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
                            "platform": "Coursera",
                            "is_native_arabic": has_arabic_char,
                            "search_position": count,
                        }

                        from src.ranking.cheap_ranker import calculate_coursera_score

                        data["score"] = calculate_coursera_score(
                            title=title,
                            tag=tag,
                            url=href,
                            search_position=count,
                            is_native_arabic=has_arabic_char,
                        )

                        candidates.append(data)
                        seen_urls.add(href)
                        count += 1

                    except Exception as inner_e:
                        continue

                print(f"    [Coursera] Found {len(candidates)} valid candidates.")

            except Exception as e:
                print(f"    [Coursera] Error: {e}")

            if language == "ar" and candidates:
                candidates.sort(key=lambda x: x["is_native_arabic"], reverse=True)

            if candidates:
                candidates_map[tag] = candidates
            else:
                print(f"    [Coursera] No results for '{tag}'")
                candidates_map[tag] = []

    except Exception as e:
        print(f"    [Coursera] Critical Error: {e}")

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
