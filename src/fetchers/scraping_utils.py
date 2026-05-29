"""
Shared scraping utilities — cookie persistence, user-agent rotation,
and Cloudflare/Turnstile detection helpers.
"""

import json
import random
from pathlib import Path

# ─── Directories ───
COOKIE_DIR = Path(__file__).resolve().parent.parent / ".cookies"

# ─── User-Agent Pool (Chrome 130-132, real desktop strings) ───
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# ─── Cloudflare / Turnstile detection signatures ───
CLOUDFLARE_TITLE_SIGS = (
    "just a moment",
    "attention required",
    "cloudflare",
    "please wait",
    "checking your browser",
)


def random_user_agent() -> str:
    """Return a random realistic User-Agent string."""
    return random.choice(USER_AGENTS)


def is_cloudflare_challenge(html: str = "", title: str = "") -> bool:
    """
    Detect Cloudflare Turnstile / WAF challenge page.
    Checks page title AND HTML body for challenge indicators.
    """
    title_lower = (title or "").lower()
    title_blocked = any(sig in title_lower for sig in CLOUDFLARE_TITLE_SIGS)

    # Check for Turnstile iframe or Cloudflare script in HTML
    html_lower = (html or "").lower()
    turnstile_present = "challenges.cloudflare.com" in html_lower
    cf_challenge_present = "cf-challenge" in html_lower or "cf_chl_opt" in html_lower

    return title_blocked or turnstile_present or cf_challenge_present


# ─── Cookie Persistence ───


def load_cookies(site_name: str) -> list:
    """Load previously saved cookies for a site from disk."""
    cookie_file = COOKIE_DIR / f"{site_name}_cookies.json"
    try:
        if cookie_file.exists():
            with open(cookie_file, "r") as f:
                cookies = json.load(f)
            print(f"    [Cookies] [{site_name}] Loaded {len(cookies)} saved cookies")
            return cookies
    except Exception as e:
        print(f"    [Cookies] [{site_name}] Failed to load cookies: {e}")
    return []


def save_cookies(site_name: str, cookies: list):
    """Save cookies to disk for session persistence."""
    cookie_file = COOKIE_DIR / f"{site_name}_cookies.json"
    try:
        COOKIE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cookie_file, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"    [Cookies] [{site_name}] Saved {len(cookies)} cookies for next run")
    except Exception as e:
        print(f"    [Cookies] [{site_name}] Failed to save cookies: {e}")


# ─── CDP Stealth Script ───
# Injected into browser pages to mask automation signals.

STEALTH_JS = """
(() => {
    // 1. Remove navigator.webdriver flag
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true
    });

    // 2. Mock Chrome runtime object
    if (!window.chrome) {
        window.chrome = {};
    }
    window.chrome.runtime = window.chrome.runtime || {};
    window.chrome.loadTimes = window.chrome.loadTimes || function() {
        return {
            commitLoadTime: Date.now() / 1000,
            connectionInfo: "h2",
            finishDocumentLoadTime: Date.now() / 1000,
            finishLoadTime: Date.now() / 1000,
            firstPaintAfterLoadTime: 0,
            firstPaintTime: Date.now() / 1000,
            navigationType: "Other",
            npnNegotiatedProtocol: "h2",
            requestTime: Date.now() / 1000,
            startLoadTime: Date.now() / 1000,
            wasAlternateProtocolAvailable: false,
            wasFetchedViaSpdy: true,
            wasNpnNegotiated: true
        };
    };
    window.chrome.csi = window.chrome.csi || function() {
        return {
            onloadT: Date.now(),
            startE: Date.now(),
            pageT: Math.random() * 1000
        };
    };

    // 3. Mock realistic plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const pluginData = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
            ];
            const plugins = Object.create(PluginArray.prototype);
            pluginData.forEach((p, i) => {
                const plugin = Object.create(Plugin.prototype);
                Object.defineProperties(plugin, {
                    name: { value: p.name },
                    filename: { value: p.filename },
                    description: { value: p.description },
                    length: { value: 0 }
                });
                plugins[i] = plugin;
            });
            Object.defineProperty(plugins, 'length', { value: pluginData.length });
            return plugins;
        },
        configurable: true
    });

    // 4. Mock languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
        configurable: true
    });

    // 5. Override permissions.query to avoid detection
    if (navigator.permissions && navigator.permissions.query) {
        const origQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (params) => {
            if (params.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission });
            }
            return origQuery(params);
        };
    }

    // 6. Prevent iframe detection of automation
    const origToString = Function.prototype.toString;
    Function.prototype.toString = function() {
        if (this === navigator.permissions.query) {
            return 'function query() { [native code] }';
        }
        return origToString.call(this);
    };
})();
"""
