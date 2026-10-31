import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
import json
import csv
import os
import urllib.parse
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import datetime

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from ollama import AsyncClient
    ollama_client = AsyncClient(host='http://localhost:11434')
except ImportError:
    ollama_client = None

# Optional curl_cffi with httpx fallback
try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    import httpx
    HAS_CURL_CFFI = False

# ---------------------------------------------------------------------------
# Constants & Regex Definitions
# ---------------------------------------------------------------------------
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
INVALID_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js')

# Hardened phone number regex
PHONE_REGEX = re.compile(
    r'(?:(?:\+44\s?(?:\(0\))?\s?[1-9]\d{1,4}\s?\d{3,6})|'
    r'(?:\b0[123789]\d{1,4}\s?\d{3,6}\b)|'
    r'(?:\+?[1-9]\d{0,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4})|'
    r'\(?\b[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b)'
)

# Social media profile regexes
LINKEDIN_REGEX = re.compile(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
INSTAGRAM_REGEX = re.compile(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
FACEBOOK_REGEX = re.compile(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
TIKTOK_REGEX = re.compile(r'https?://(?:www\.)?tiktok\.com/@[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
X_REGEX = re.compile(r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+/?', re.IGNORECASE)

# 12-Column Schema Definition
EXPORT_HEADERS = [
    "Company Name", "Domain", "Email", "Phone", "WhatsApp",
    "Facebook", "Instagram", "LinkedIn", "TikTok", "Address",
    "Category", "Date Added"
]

CSV_SUPPORT_BANNER = [
    [
        "If LeadDirect-MCP saves your team from monthly SaaS subscriptions or cuts your LLM token spend, consider backing ongoing development. Your support keeps these local AI and OSINT tools free and actively maintained. Support via Patreon: https://www.patreon.com/netizen4_bit"
    ],
    [
        "Need a Custom B2B Automation or Agentic Pipeline? Need a tailored MCP server, private OSINT enrichment module, or autonomous Agentic workflow built specifically for your company? Reach out via Linkdin: https://www.linkedin.com/in/nihatkasim for custom integration and consulting."
    ],
    []
]


# ---------------------------------------------------------------------------
# Utility Functions: Domain, Phone & Cloudflare
# ---------------------------------------------------------------------------

def clean_domain(domain: str) -> str:
    """Normalizes domain by removing protocol, www., and trailing paths."""
    if not domain:
        return ""
    d = str(domain).strip().lower()
    for prefix in ("https://", "http://", "www."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.rstrip("/").split("/")[0]


def is_valid_phone(phone_str: str) -> bool:
    """Hardened phone number validator:
    - Rejects prices ($ / £ / € / .00) and decimal numbers/coordinates (e.g. 51.876)
    - Rejects year ranges (e.g. 2005-2011, 2011-2016)
    - Rejects strings starting with 2020-2029 (ISO dates/timestamps: YYYYMMDD, YYYYMMDDhhmmss) unless preceded by '+'
    - Rejects unix timestamps (10 or 13 digits starting with 16, 17, 18) unless preceded by '+'
    - Rejects strings with 6+ identical repeating digits (e.g. 3333333333, 0000000000)
    - Rejects sequential digit strings (e.g. 1234567890)
    - Rejects strings with fewer than 7 or more than 15 digits
    - Rejects strings with <= 2 distinct digits in an 8+ digit number
    - Rejects incomplete UK numbers (01, 02, 03, 07 must be 10 or 11 digits)
    """
    if not phone_str:
        return False
    raw = str(phone_str).strip()

    # Reject prices / coordinates (e.g. 51.876326746207, 250.00)
    if any(c in raw for c in ("$", "£", "€", "¥")) or ".00" in raw or ",00" in raw:
        return False
    if re.search(r'\.\d{2,}', raw):
        return False

    # Reject year ranges (e.g. 2005-2011, 2011-2016, 2020-2024)
    if re.search(r'\b(19\d\d|20\d\d)[\s\-]*(19\d\d|20\d\d)\b', raw):
        return False

    digits = re.sub(r'\D', '', raw)

    if len(digits) < 7 or len(digits) > 15:
        return False

    # Reject 6+ identical repeating digits
    if re.search(r'(\d)\1{5,}', digits):
        return False

    # Reject sequential numbers
    if digits in ("1234567890", "0123456789", "9876543210", "0987654321"):
        return False

    # Reject any digit string starting with 2020-2029 (ISO timestamps/dates: YYYYMMDD, YYYYMMDDhhmmss) unless preceded by '+'
    if not raw.startswith("+"):
        if digits.startswith(("2020", "2021", "2022", "2023", "2024", "2025", "2026", "2027", "2028", "2029")):
            return False

    # Reject unix epoch timestamps (10 or 13 digits starting with 16, 17, 18) unless preceded by '+'
    if not raw.startswith("+") and len(digits) in (10, 13) and digits.startswith(("16", "17", "18")):
        return False

    # Reject if <= 2 distinct digits in an 8+ digit string (e.g. 00000000)
    if len(set(digits)) <= 2 and len(digits) >= 8:
        return False

    # Specific UK check: UK numbers starting with 01, 02, 03, 07 must be 10 or 11 digits
    if raw.startswith(("01", "02", "03", "07", "08")):
        if len(digits) not in (10, 11):
            return False

    return True


def extract_phone_numbers(html: str, text: str = "") -> list[str]:
    """Extracts phone numbers prioritizing tel: href links and validated local/international numbers."""
    phones = []
    seen_digits = set()

    clean_text_parts = []
    if text:
        clean_text_parts.append(text)

    # 1. Prioritize tel: and callto: links in HTML
    if html:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.lower().startswith(("tel:", "callto:")):
                    raw_phone = href.split(":", 1)[-1].split("?")[0].strip()
                    raw_phone = urllib.parse.unquote(raw_phone).strip()
                    if is_valid_phone(raw_phone):
                        d = re.sub(r'\D', '', raw_phone)
                        if d not in seen_digits:
                            seen_digits.add(d)
                            phones.append(raw_phone)

            # Strip scripts, styles, svg to prevent CSS values or JS version numbers from matching
            for tag in soup(["script", "style", "svg", "noscript"]):
                tag.extract()
            body_text = soup.get_text(separator=" ", strip=True)
            if body_text:
                clean_text_parts.append(body_text)
        except Exception:
            pass

    # 2. Extract from clean visible text using hardened regex
    combined_text = " ".join(clean_text_parts).replace("\xa0", " ")
    for match in PHONE_REGEX.finditer(combined_text):
        candidate = match.group(0).strip()
        if is_valid_phone(candidate):
            d = re.sub(r'\D', '', candidate)
            if d not in seen_digits:
                seen_digits.add(d)
                phones.append(candidate)

    return phones


def decode_cf_email(encoded_string: str) -> str:
    """Decode a Cloudflare-obfuscated email string."""
    try:
        key = int(encoded_string[:2], 16)
        decoded = []
        for i in range(2, len(encoded_string), 2):
            char_code = int(encoded_string[i : i + 2], 16) ^ key
            decoded.append(chr(char_code))
        return "".join(decoded)
    except Exception:
        return ""


def extract_cf_emails(html: str) -> list[str]:
    """Find and decode all Cloudflare-protected emails in an HTML document."""
    soup = BeautifulSoup(html, "html.parser")
    emails = []

    for tag in soup.find_all(attrs={"data-cfemail": True}):
        try:
            decoded = decode_cf_email(tag["data-cfemail"])
            if decoded and "@" in decoded:
                emails.append(decoded.lower())
        except Exception:
            pass

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/cdn-cgi/l/email-protection#" in href:
            hex_part = href.split("#", 1)[-1]
            try:
                decoded = decode_cf_email(hex_part)
                if decoded and "@" in decoded:
                    emails.append(decoded.lower())
            except Exception:
                pass

    return list(set(emails))


def is_valid_email(email: str) -> bool:
    """Filter out image assets or scripts matching email regex."""
    clean = email.strip().lower()
    return not clean.endswith(INVALID_EXTENSIONS) and "@" in clean


# ---------------------------------------------------------------------------
# Deep Social Media & WhatsApp Extraction
# ---------------------------------------------------------------------------

def extract_whatsapp(html_or_text: str) -> str:
    """Extracts direct WhatsApp links (wa.me/<number>, api.whatsapp.com/send?phone=<number>, whatsapp://send?phone=)
    as well as phone numbers labeled near 'WhatsApp' in HTML or text.
    Returns normalized https://wa.me/<number> or empty string.
    """
    if not html_or_text:
        return ""

    # 1. Direct link detection
    direct_patterns = [
        r'(?:https?://)?(?:wa\.me/(?:\+)?|api\.whatsapp\.com/send\?(?:[^&]*&)?phone=|web\.whatsapp\.com/send\?(?:[^&]*&)?phone=)([0-9]{7,15})',
        r'whatsapp://send\?(?:[^&]*&)?phone=(\+?[0-9]{7,15})',
    ]
    for pat in direct_patterns:
        m = re.search(pat, html_or_text, re.IGNORECASE)
        if m:
            raw_num = m.group(1).lstrip("+")
            if is_valid_phone(raw_num):
                return f"https://wa.me/{raw_num}"

    # 2. Text proximity detection ("WhatsApp: +44 ...")
    wa_text_pattern = r'(?i)(?:whatsapp|chat\s+(?:with\s+us\s+)?on\s+whatsapp)[^0-9+]{1,30}(\+?[0-9\s\-\(\)\.]{7,18})'
    m2 = re.search(wa_text_pattern, html_or_text)
    if m2:
        candidate = m2.group(1).strip()
        if is_valid_phone(candidate):
            digits = re.sub(r'\D', '', candidate)
            return f"https://wa.me/{digits}"

    return ""


def normalize_social_url(platform: str, url: str) -> str:
    """Normalizes company profile URLs for Facebook, Instagram, LinkedIn, and TikTok,
    filtering out sharers, plugins, post IDs, and reels.
    """
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if platform == "facebook":
        ignore = ["sharer", "share.php", "plugins", "dialog", "tr?", "login", "recover", "help", "policies"]
        if any(x in url.lower() for x in ignore):
            return ""
        if "profile.php" in path and parsed.query:
            m = re.search(r'id=(\d+)', parsed.query)
            if m:
                return f"https://www.facebook.com/profile.php?id={m.group(1)}"
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ""
        page = parts[0]
        if page in ("pages", "group", "groups", "people") and len(parts) > 1:
            page = "/".join(parts[:2])
        if not re.match(r'^[a-zA-Z0-9_\-\./]+$', page):
            return ""
        return f"https://www.facebook.com/{page}"

    elif platform == "instagram":
        ignore = ["/p/", "/reel/", "/reels/", "/stories/", "/explore/", "/tv/", "/accounts/", "/legal"]
        if any(x in url.lower() for x in ignore):
            return ""
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ""
        handle = parts[0].lstrip("@")
        return f"https://www.instagram.com/{handle}"

    elif platform == "linkedin":
        ignore = ["/share", "/sharing", "/pulse", "/posts", "/feed", "/jobs"]
        if any(x in url.lower() for x in ignore):
            return ""
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("company", "in", "school"):
            return f"https://www.linkedin.com/{parts[0]}/{parts[1]}"
        elif len(parts) == 1 and parts[0] not in ("company", "in", "school", "feed"):
            return f"https://www.linkedin.com/company/{parts[0]}"
        return ""

    elif platform == "tiktok":
        ignore = ["/video/", "/share", "/tag/", "/live/"]
        if any(x in url.lower() for x in ignore):
            return ""
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ""
        handle = parts[0]
        if not handle.startswith("@"):
            handle = "@" + handle
        return f"https://www.tiktok.com/{handle}"

    return url


def extract_social_links(html_or_text: str) -> dict:
    """Extracts verified and normalized social media profiles (LinkedIn, Instagram, Facebook, TikTok, X, WhatsApp)."""
    socials = {
        "linkedin": [],
        "instagram": [],
        "facebook": [],
        "tiktok": [],
        "x": [],
        "whatsapp": []
    }

    # 1. Check anchor hrefs if HTML
    try:
        soup = BeautifulSoup(html_or_text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            if "linkedin.com" in low:
                norm = normalize_social_url("linkedin", href)
                if norm and norm not in socials["linkedin"]:
                    socials["linkedin"].append(norm)
            elif "instagram.com" in low:
                norm = normalize_social_url("instagram", href)
                if norm and norm not in socials["instagram"]:
                    socials["instagram"].append(norm)
            elif "facebook.com" in low:
                norm = normalize_social_url("facebook", href)
                if norm and norm not in socials["facebook"]:
                    socials["facebook"].append(norm)
            elif "tiktok.com" in low:
                norm = normalize_social_url("tiktok", href)
                if norm and norm not in socials["tiktok"]:
                    socials["tiktok"].append(norm)
            elif "twitter.com" in low or "x.com" in low:
                norm = href.split("?")[0].rstrip("/")
                if norm not in socials["x"]:
                    socials["x"].append(norm)
    except Exception:
        pass

    # 2. Fallback regexes
    for match in LINKEDIN_REGEX.findall(html_or_text):
        norm = normalize_social_url("linkedin", match)
        if norm and norm not in socials["linkedin"]:
            socials["linkedin"].append(norm)

    for match in INSTAGRAM_REGEX.findall(html_or_text):
        norm = normalize_social_url("instagram", match)
        if norm and norm not in socials["instagram"]:
            socials["instagram"].append(norm)

    for match in FACEBOOK_REGEX.findall(html_or_text):
        norm = normalize_social_url("facebook", match)
        if norm and norm not in socials["facebook"]:
            socials["facebook"].append(norm)

    for match in TIKTOK_REGEX.findall(html_or_text):
        norm = normalize_social_url("tiktok", match)
        if norm and norm not in socials["tiktok"]:
            socials["tiktok"].append(norm)

    for match in X_REGEX.findall(html_or_text):
        norm = match.split("?")[0].rstrip("/")
        if norm and norm not in socials["x"]:
            socials["x"].append(norm)

    # 3. WhatsApp detection
    wa = extract_whatsapp(html_or_text)
    if wa and wa not in socials["whatsapp"]:
        socials["whatsapp"].append(wa)

    return socials


def search_social_fallback(company_name: str = "", domain: str = "") -> dict:
    """Lightweight targeted DuckDuckGo query fallback:
    site:facebook.com OR site:instagram.com OR site:linkedin.com "<company_name>" OR "<domain>"
    to capture official social pages when not linked on the homepage.
    """
    found = {
        "facebook": "",
        "instagram": "",
        "linkedin": "",
        "tiktok": "",
        "whatsapp": ""
    }

    terms = []
    clean_d = clean_domain(domain)
    c_name = company_name.strip() if company_name and company_name.lower() not in ("unknown", "n/a", "none") else ""

    if c_name:
        terms.append(f'"{c_name}"')
    if clean_d:
        terms.append(f'"{clean_d}"')

    if not terms:
        return found

    query_target = " OR ".join(terms)
    ddg_query = f'site:facebook.com OR site:instagram.com OR site:linkedin.com {query_target}'

    try:
        from ddgs import DDGS
        results = list(DDGS().text(ddg_query, max_results=6))
        for r in results:
            href = r.get("href", "")
            low = href.lower()
            if "facebook.com" in low and not found["facebook"]:
                norm = normalize_social_url("facebook", href)
                if norm:
                    found["facebook"] = norm
            elif "instagram.com" in low and not found["instagram"]:
                norm = normalize_social_url("instagram", href)
                if norm:
                    found["instagram"] = norm
            elif "linkedin.com" in low and not found["linkedin"]:
                norm = normalize_social_url("linkedin", href)
                if norm:
                    found["linkedin"] = norm
            elif "tiktok.com" in low and not found["tiktok"]:
                norm = normalize_social_url("tiktok", href)
                if norm:
                    found["tiktok"] = norm
            elif "wa.me" in low and not found["whatsapp"]:
                wa = extract_whatsapp(href)
                if wa:
                    found["whatsapp"] = wa
    except Exception:
        try:
            from ddgs import DDGS
            if c_name:
                results = list(DDGS().text(f'"{c_name}" site:facebook.com', max_results=2))
                for r in results:
                    norm = normalize_social_url("facebook", r.get("href", ""))
                    if norm and not found["facebook"]:
                        found["facebook"] = norm
        except Exception:
            pass

    return found


# ---------------------------------------------------------------------------
# 1. 2-Tier Scraping Waterfall (Tier 1 curl_cffi -> Tier 2 Playwright)
# ---------------------------------------------------------------------------

async def fetch_tier1_static(url: str, timeout: int = 10) -> tuple[int, str]:
    """Tier 1: Fast static scrape using curl_cffi, httpx, or requests fallback."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    if HAS_CURL_CFFI:
        try:
            async with CurlAsyncSession(impersonate="chrome120", timeout=timeout) as session:
                resp = await session.get(url, allow_redirects=True, headers=headers)
                return resp.status_code, resp.text
        except Exception:
            pass

    # Fallback to standard httpx
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.text:
                return resp.status_code, resp.text
    except Exception:
        pass

    # Fallback to requests (handles servers with strict HTTP/2 or TLS handshakes)
    try:
        import requests
        loop = asyncio.get_running_loop()
        def _sync_req():
            return requests.get(url, timeout=timeout, headers=headers)
        r = await loop.run_in_executor(None, _sync_req)
        return r.status_code, r.text
    except Exception:
        pass

    return 0, ""


async def scrape_company_data(base_url: str, p_browser=None) -> dict:
    """Scrapes company base URL and common subpages using a 2-Tier Waterfall:
    - Tier 1: Static Fast-Pass (curl_cffi with chrome120 impersonation + BeautifulSoup)
    - Tier 2: Dynamic Fallback (Playwright) if Tier 1 encounters bot challenge or empty JS shell.
    Extracts emails, hardened phones, WhatsApp, and normalized social media profiles.
    """
    clean_base = base_url if base_url.startswith("http") else f"https://{base_url}"
    pages_to_visit = [
        clean_base,
        urljoin(clean_base, '/contact'),
        urljoin(clean_base, '/contact-us'),
        urljoin(clean_base, '/about'),
        urljoin(clean_base, '/about-us'),
        urljoin(clean_base, '/team'),
        urljoin(clean_base, '/staff')
    ]

    emails = set()
    phones = []
    socials = {"linkedin": [], "instagram": [], "facebook": [], "tiktok": [], "x": [], "whatsapp": []}
    whatsapp_link = ""
    raw_text_chunks = []
    tier_used = "tier1_static"
    needs_tier2 = False

    # --- TIER 1: Static Fast-Pass ---
    for url in pages_to_visit:
        status_code, html = await fetch_tier1_static(url, timeout=10)

        # Check if Tier 1 was blocked or hit Cloudflare challenge
        if status_code in (403, 503) or "challenge-platform" in html or "cf-browser-verification" in html:
            needs_tier2 = True
            break

        if html:
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(separator=" ", strip=True)
            if text:
                raw_text_chunks.append(text[:1500])

            # 1. Regex emails & mailto links
            for e in EMAIL_REGEX.findall(html + " " + text):
                if is_valid_email(e):
                    emails.add(e.lower())
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.lower().startswith("mailto:"):
                    raw_mail = href.split(":", 1)[-1].split("?")[0].strip()
                    if is_valid_email(raw_mail):
                        emails.add(raw_mail.lower())

            # 2. Cloudflare decoded emails
            for cf_e in extract_cf_emails(html):
                if is_valid_email(cf_e):
                    emails.add(cf_e.lower())

            # 3. Hardened Phones (prioritizing tel: links and excluding timestamps)
            extracted_p = extract_phone_numbers(html, text)
            for p in extracted_p:
                if p not in phones:
                    phones.append(p)

            # 4. WhatsApp
            wa = extract_whatsapp(html + " " + text)
            if wa and not whatsapp_link:
                whatsapp_link = wa

            # 5. Social links
            found_socials = extract_social_links(html)
            for network, links in found_socials.items():
                for link in links:
                    if link not in socials[network]:
                        socials[network].append(link)

    # If Tier 1 found zero contacts on a likely JS-rendered shell, trigger Tier 2
    if len(emails) == 0 and len(phones) == 0 and not raw_text_chunks:
        needs_tier2 = True

    # --- TIER 2: Dynamic Fallback (Playwright) ---
    if needs_tier2:
        tier_used = "tier2_playwright"
        created_browser = False
        browser = p_browser
        playwright_instance = None

        if not browser:
            playwright_instance = await async_playwright().start()
            browser = await playwright_instance.chromium.launch(headless=True)
            created_browser = True

        try:
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                ignore_https_errors=True
            )
            for url in pages_to_visit[:4]:  # Prioritize main + contact/about in dynamic fallback
                page = await context.new_page()
                try:
                    await page.goto(url, timeout=12000, wait_until='domcontentloaded')
                    text = await page.evaluate('document.body.innerText')
                    html_content = await page.content()

                    if text:
                        raw_text_chunks.append(text[:1500])
                        for e in EMAIL_REGEX.findall(text + " " + html_content):
                            if is_valid_email(e):
                                emails.add(e.lower())

                    # Phones
                    extracted_p = extract_phone_numbers(html_content, text or "")
                    for p in extracted_p:
                        if p not in phones:
                            phones.append(p)

                    # WhatsApp
                    wa = extract_whatsapp(html_content + " " + (text or ""))
                    if wa and not whatsapp_link:
                        whatsapp_link = wa

                    # Extract social links from dynamic DOM
                    found_socials = extract_social_links(html_content)
                    for network, links in found_socials.items():
                        for link in links:
                            if link not in socials[network]:
                                socials[network].append(link)
                except Exception:
                    pass
                finally:
                    await page.close()
            await context.close()
        finally:
            if created_browser:
                await browser.close()
                if playwright_instance:
                    await playwright_instance.stop()

    # --- Social Search Fallback if no socials found on site ---
    if not socials["facebook"] and not socials["instagram"] and not socials["linkedin"] and not whatsapp_link:
        domain = clean_domain(base_url)
        fallback = search_social_fallback("", domain)
        for net, link in fallback.items():
            if link and not socials.get(net):
                socials[net] = [link]
        if fallback.get("whatsapp") and not whatsapp_link:
            whatsapp_link = fallback["whatsapp"]

    if not whatsapp_link and socials.get("whatsapp"):
        whatsapp_link = socials["whatsapp"][0]

    return {
        'emails': sorted(list(emails)),
        'phones': phones,
        'whatsapp': whatsapp_link,
        'socials': socials,
        'raw_text': " ".join(raw_text_chunks)[:4000],
        'tier_used': tier_used
    }


# ---------------------------------------------------------------------------
# 2. Google Maps B2B Scraper Tool
# ---------------------------------------------------------------------------

async def scrape_google_maps_b2b(query: str, target_leads: int = 10) -> list[dict]:
    """Searches Google Maps for local/regional B2B businesses, dealers, physical warehouses,
    extracts: company_name, website_url, domain, phone, address, and category.
    """
    results = []
    seen_names = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US"
        )
        page = await context.new_page()
        maps_url = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}?hl=en"

        try:
            await page.goto(maps_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)

            # Handle Google cookie consent modal if present
            try:
                consent_btn = page.locator('button:has-text("Accept all"), button:has-text("I agree"), form[action*="consent"] button')
                if await consent_btn.first.is_visible(timeout=2500):
                    await consent_btn.first.click()
                    await page.wait_for_timeout(1500)
            except Exception:
                pass

            feed = page.locator('div[role="feed"]')
            max_scroll_attempts = 15

            for _ in range(max_scroll_attempts):
                cards = await feed.locator('> div').all()
                for card in cards:
                    text = (await card.inner_text()).strip()
                    if not text:
                        continue
                    lines = [l.strip() for l in text.split('\n') if l.strip()]

                    # Check for place link
                    place_link = card.locator('a[href*="/maps/place/"]')
                    if await place_link.count() == 0:
                        continue

                    name = await place_link.first.get_attribute('aria-label') or lines[0]
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)

                    # Extract website link
                    web_link = card.locator('a[aria-label*="website" i], a[href^="http"]:not([href*="google.com"])')
                    website = None
                    if await web_link.count() > 0:
                        website = await web_link.first.get_attribute('href')

                    domain = urlparse(website).netloc.replace('www.', '').lower() if website else None

                    # Extract category, address, phone from text lines
                    category = None
                    address = None
                    phone = None
                    for line in lines[1:]:
                        if '·' in line:
                            parts = [p.strip() for p in line.split('·') if p.strip()]
                            if parts:
                                if not category and len(parts) > 0 and not any(ord(c) > 0xe000 for c in parts[0]):
                                    category = parts[0]
                                if not address and len(parts) > 1 and not any(ord(c) > 0xe000 for c in parts[-1]):
                                    address = parts[-1]
                        if '+' in line or any(c.isdigit() for c in line):
                            m = re.search(r'(\+?\d[\d\s\-\(\)\/]{7,}\d)', line)
                            if m and not phone:
                                cand = m.group(1).strip()
                                if is_valid_phone(cand):
                                    phone = cand

                    results.append({
                        "company_name": name,
                        "website_url": website,
                        "domain": domain,
                        "phone": phone,
                        "whatsapp": "",
                        "facebook": "",
                        "instagram": "",
                        "linkedin": "",
                        "tiktok": "",
                        "address": address,
                        "category": category
                    })

                    if len(results) >= target_leads:
                        break

                if len(results) >= target_leads:
                    break

                # Scroll down in the results feed to load more cards
                try:
                    await feed.evaluate('el => el.scrollBy(0, 1000)')
                    await page.wait_for_timeout(1500)
                except Exception:
                    break

        except Exception as e:
            print(f"[!] Google Maps scraping error: {e}")
        finally:
            await browser.close()

    return results


async def normalize_with_llm(company_name, raw_text):
    """Use local Qwen purely for normalization and entity extraction from raw text"""
    prompt = (
        f"Company: {company_name}\n"
        f"Raw Scraped Text: {raw_text}\n\n"
        "Task: Provide a 1-2 sentence summary of what this company does, and a list of up to 3 industry tags. "
        "Output strictly in valid JSON format exactly like this:\n"
        "{\n  \"summary\": \"Summary text here.\",\n  \"tags\": [\"Tag1\", \"Tag2\"]\n}\n"
        "Do not include any other text or markdown blocks."
    )
    try:
        response = await ollama_client.chat(
            model='my-custom-qwen',
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.0}
        )
        content = response['message']['content'].strip()
        if content.startswith('```json'):
            content = content.replace('```json', '', 1)
        if content.endswith('```'):
            content = content[::-1].replace('```', '', 1)[::-1]
        data = json.loads(content.strip())
        return data.get('summary', ''), ", ".join(data.get('tags', []))
    except Exception as e:
        print(f"    [!] LLM normalization failed for {company_name}: {e}")
        return "", ""


# ---------------------------------------------------------------------------
# 12-Column Exporter & Upserter Engine
# ---------------------------------------------------------------------------

def get_desktop_dir() -> str:
    """Resolves the user's Desktop directory across Windows, macOS, and Linux."""
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive and os.path.isdir(os.path.join(onedrive, "Desktop")):
        return os.path.join(onedrive, "Desktop")
    std_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(std_desktop):
        return std_desktop
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def save_leads_to_excel_and_csv(leads: list[dict], excel_file: str = None, csv_file: str = None) -> tuple[str, str]:
    """Saves or appends leads to both a formatted Excel (.xlsx) file and a CSV file using the 12-column schema."""
    output_dir = os.environ.get("LEADDIRECT_OUTPUT_DIR") or os.path.join(get_desktop_dir(), "LeadDirect_Leads")
    os.makedirs(output_dir, exist_ok=True)

    excel_path = excel_file or os.environ.get("LEADDIRECT_EXCEL_OUTPUT") or os.path.join(output_dir, "LeadDirect_B2B_Leads.xlsx")
    csv_path = csv_file or os.environ.get("LEADDIRECT_CSV_OUTPUT") or os.path.join(output_dir, "leads_output.csv")

    upsert_lead_to_excel_and_csv(leads, excel_path=excel_path, csv_path=csv_path)
    return excel_path, csv_path


def upsert_lead_to_excel_and_csv(leads_or_lead: list[dict] | dict, excel_path: str = None, csv_path: str = None) -> tuple[str, str]:
    """Upserts and merges lead fields into matching Domain row in Excel and CSV using the 12-column schema."""
    output_dir = os.environ.get("LEADDIRECT_OUTPUT_DIR") or os.path.join(get_desktop_dir(), "LeadDirect_Leads")
    os.makedirs(output_dir, exist_ok=True)

    excel_file = excel_path or os.environ.get("LEADDIRECT_EXCEL_OUTPUT") or os.path.join(output_dir, "LeadDirect_B2B_Leads.xlsx")
    csv_file = csv_path or os.environ.get("LEADDIRECT_CSV_OUTPUT") or os.path.join(output_dir, "leads_output.csv")

    leads = leads_or_lead if isinstance(leads_or_lead, list) else [leads_or_lead]
    today_str = str(datetime.date.today())

    # --- 1. Update / Merge Excel ---
    if HAS_OPENPYXL:
        try:
            if os.path.exists(excel_file):
                wb = openpyxl.load_workbook(excel_file)
                ws = wb.active
            else:
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "B2B Leads"

            # Check if existing sheet needs migration from 7 columns to 12
            if ws.max_row >= 4:
                r4_col5 = ws.cell(row=4, column=5).value
                if r4_col5 == "Address" or ws.max_column < 12:
                    for r in range(5, ws.max_row + 1):
                        old_addr = ws.cell(row=r, column=5).value
                        old_cat = ws.cell(row=r, column=6).value
                        old_date = ws.cell(row=r, column=7).value
                        for c in range(5, 10):
                            ws.cell(row=r, column=c).value = ""
                        ws.cell(row=r, column=10).value = old_addr or "N/A"
                        ws.cell(row=r, column=11).value = old_cat or "Distributor / Wholesaler"
                        ws.cell(row=r, column=12).value = old_date or today_str

            if ws.max_row < 4:
                ws.merge_cells("A1:L1")
                t_cell = ws["A1"]
                t_cell.value = "LeadDirect-MCP | Autonomous B2B Leads Engine"
                t_cell.font = Font(name="Segoe UI", size=12, bold=True, color="FFFFFF")
                t_cell.fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
                t_cell.alignment = Alignment(horizontal="center", vertical="center")
                ws.row_dimensions[1].height = 25

                ws.merge_cells("A2:L2")
                b_cell = ws["A2"]
                b_cell.value = "Support research via Patreon: https://www.patreon.com/netizen4_bit  |  Custom B2B Integrations & Consulting: https://www.linkedin.com/in/nihatkasim"
                b_cell.font = Font(name="Segoe UI", size=9, italic=True, color="1D4ED8")
                b_cell.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
                b_cell.alignment = Alignment(horizontal="center", vertical="center")
                ws.row_dimensions[2].height = 20
                ws.row_dimensions[3].height = 8
            else:
                try:
                    ws.unmerge_cells("A1:G1")
                except Exception:
                    pass
                try:
                    ws.merge_cells("A1:L1")
                except Exception:
                    pass
                try:
                    ws.unmerge_cells("A2:G2")
                except Exception:
                    pass
                try:
                    ws.merge_cells("A2:L2")
                except Exception:
                    pass

            # Write 12 headers at row 4
            for col_idx, h in enumerate(EXPORT_HEADERS, 1):
                cell = ws.cell(row=4, column=col_idx, value=h)
                cell.font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
                cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[4].height = 22

            # Map existing domains to rows
            domain_to_row = {}
            for r in range(5, ws.max_row + 1):
                d_val = clean_domain(ws.cell(row=r, column=2).value)
                if d_val:
                    domain_to_row[d_val] = r

            for lead in leads:
                target_domain = clean_domain(lead.get("domain", ""))
                existing_row = domain_to_row.get(target_domain) if target_domain else None

                if existing_row:
                    r = existing_row
                    c_name = lead.get("company") or lead.get("company_name")
                    if c_name and (not ws.cell(row=r, column=1).value or ws.cell(row=r, column=1).value in ("Unknown", "")):
                        ws.cell(row=r, column=1).value = c_name

                    n_email = lead.get("email")
                    curr_email = str(ws.cell(row=r, column=3).value or "").strip()
                    if n_email and n_email not in ("Website Form", "Not Found", "N/A", ""):
                        if curr_email in ("Website Form", "Not Found", "N/A", "") or "@" not in curr_email:
                            ws.cell(row=r, column=3).value = n_email

                    n_phone = lead.get("phone")
                    curr_phone = str(ws.cell(row=r, column=4).value or "").strip()
                    if n_phone and is_valid_phone(n_phone):
                        if not is_valid_phone(curr_phone) or curr_phone in ("Not Found", "N/A", ""):
                            ws.cell(row=r, column=4).value = n_phone

                    n_wa = lead.get("whatsapp")
                    if n_wa and not ws.cell(row=r, column=5).value:
                        ws.cell(row=r, column=5).value = n_wa

                    n_fb = lead.get("facebook")
                    if n_fb and not ws.cell(row=r, column=6).value:
                        ws.cell(row=r, column=6).value = n_fb

                    n_ig = lead.get("instagram")
                    if n_ig and not ws.cell(row=r, column=7).value:
                        ws.cell(row=r, column=7).value = n_ig

                    n_li = lead.get("linkedin")
                    if n_li and not ws.cell(row=r, column=8).value:
                        ws.cell(row=r, column=8).value = n_li

                    n_tt = lead.get("tiktok")
                    if n_tt and not ws.cell(row=r, column=9).value:
                        ws.cell(row=r, column=9).value = n_tt

                    n_addr = lead.get("address")
                    if n_addr and n_addr != "N/A" and ws.cell(row=r, column=10).value in ("N/A", "", None):
                        ws.cell(row=r, column=10).value = n_addr

                    n_cat = lead.get("category")
                    if n_cat and n_cat != "Distributor / Wholesaler" and ws.cell(row=r, column=11).value in ("Distributor / Wholesaler", "", None):
                        ws.cell(row=r, column=11).value = n_cat
                else:
                    new_r = max(ws.max_row + 1, 5)
                    row_vals = [
                        lead.get("company") or lead.get("company_name", "Unknown"),
                        lead.get("domain", "") or "",
                        lead.get("email", "Website Form") or "Website Form",
                        lead.get("phone", "Not Found") or "Not Found",
                        lead.get("whatsapp", "") or "",
                        lead.get("facebook", "") or "",
                        lead.get("instagram", "") or "",
                        lead.get("linkedin", "") or "",
                        lead.get("tiktok", "") or "",
                        lead.get("address", "N/A") or "N/A",
                        lead.get("category", "Distributor / Wholesaler") or "Distributor / Wholesaler",
                        lead.get("date_added") or today_str,
                    ]
                    for col_idx, val in enumerate(row_vals, 1):
                        c = ws.cell(row=new_r, column=col_idx, value=val)
                        c.font = Font(name="Segoe UI", size=10)
                        c.alignment = Alignment(vertical="center")
                    ws.row_dimensions[new_r].height = 20
                    if target_domain:
                        domain_to_row[target_domain] = new_r

            for col in ws.columns:
                col_letter = get_column_letter(col[0].column)
                max_l = max(len(str(cell.value or "")) for cell in col if cell.row >= 4)
                ws.column_dimensions[col_letter].width = max(max_l + 4, 15)

            ws.freeze_panes = "A5"
            if ws.max_row >= 5:
                ws.auto_filter.ref = f"A4:L{ws.max_row}"

            wb.save(excel_file)
        except Exception as e:
            print(f"Warning: Failed to update Excel file: {e}")

    # --- 2. Update / Merge CSV ---
    try:
        existing_rows = []
        banner_rows = []
        has_headers = False

        if os.path.exists(csv_file):
            with open(csv_file, "r", encoding="utf-8", newline="") as f:
                reader = list(csv.reader(f))

            data_start = False
            for r in reader:
                if not r:
                    if not data_start:
                        banner_rows.append(r)
                    continue
                col0 = r[0].strip().lower()
                if not data_start and (col0.startswith("if leaddirect") or col0.startswith("need a custom") or col0.startswith("#")):
                    banner_rows.append(r)
                elif not data_start and ("company" in col0):
                    data_start = True
                    has_headers = True
                elif data_start:
                    if len(r) == 7:
                        migrated = [
                            r[0], r[1], r[2], r[3],
                            "", "", "", "", "",
                            r[4], r[5], r[6]
                        ]
                        existing_rows.append(migrated)
                    elif len(r) < 12:
                        migrated = r + [""] * (12 - len(r))
                        existing_rows.append(migrated)
                    else:
                        existing_rows.append(r[:12])

        if not banner_rows:
            banner_rows = CSV_SUPPORT_BANNER

        domain_map = {}
        for idx, row in enumerate(existing_rows):
            if len(row) > 1:
                d = clean_domain(row[1])
                if d:
                    domain_map[d] = idx

        for lead in leads:
            d = clean_domain(lead.get("domain", ""))
            if d and d in domain_map:
                idx = domain_map[d]
                row = existing_rows[idx]
                c_name = lead.get("company") or lead.get("company_name")
                if c_name and (not row[0] or row[0] in ("Unknown", "")):
                    row[0] = c_name
                n_email = lead.get("email")
                if n_email and n_email not in ("Website Form", "Not Found", "N/A", ""):
                    if row[2] in ("Website Form", "Not Found", "N/A", "") or "@" not in row[2]:
                        row[2] = n_email
                n_phone = lead.get("phone")
                if n_phone and is_valid_phone(n_phone):
                    if not is_valid_phone(row[3]) or row[3] in ("Not Found", "N/A", ""):
                        row[3] = n_phone
                n_wa = lead.get("whatsapp")
                if n_wa and not row[4]:
                    row[4] = n_wa
                n_fb = lead.get("facebook")
                if n_fb and not row[5]:
                    row[5] = n_fb
                n_ig = lead.get("instagram")
                if n_ig and not row[6]:
                    row[6] = n_ig
                n_li = lead.get("linkedin")
                if n_li and not row[7]:
                    row[7] = n_li
                n_tt = lead.get("tiktok")
                if n_tt and not row[8]:
                    row[8] = n_tt
                n_addr = lead.get("address")
                if n_addr and n_addr != "N/A" and row[9] in ("N/A", "", None):
                    row[9] = n_addr
                n_cat = lead.get("category")
                if n_cat and n_cat != "Distributor / Wholesaler" and row[10] in ("Distributor / Wholesaler", "", None):
                    row[10] = n_cat
            else:
                new_row = [
                    lead.get("company") or lead.get("company_name", "Unknown"),
                    lead.get("domain", "") or "",
                    lead.get("email", "Website Form") or "Website Form",
                    lead.get("phone", "Not Found") or "Not Found",
                    lead.get("whatsapp", "") or "",
                    lead.get("facebook", "") or "",
                    lead.get("instagram", "") or "",
                    lead.get("linkedin", "") or "",
                    lead.get("tiktok", "") or "",
                    lead.get("address", "N/A") or "N/A",
                    lead.get("category", "Distributor / Wholesaler") or "Distributor / Wholesaler",
                    lead.get("date_added") or today_str,
                ]
                existing_rows.append(new_row)
                if d:
                    domain_map[d] = len(existing_rows) - 1

        os.makedirs(os.path.dirname(os.path.abspath(csv_file)), exist_ok=True)
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for b in banner_rows:
                writer.writerow(b)
            writer.writerow(EXPORT_HEADERS)
            for r in existing_rows:
                writer.writerow(r)
    except Exception as e:
        print(f"Warning: Failed to update CSV file: {e}")

    return excel_file, csv_file


# ---------------------------------------------------------------------------
# CLI / Standalone Runner
# ---------------------------------------------------------------------------

async def main():
    query = "packaging distributors munich"
    print(f"Searching Google Maps B2B for: {query}")
    leads = await scrape_google_maps_b2b(query, target_leads=5)
    print(f"Found {len(leads)} leads:")
    for l in leads:
        print(l)

if __name__ == "__main__":
    asyncio.run(main())
