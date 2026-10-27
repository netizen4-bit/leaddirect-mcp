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

# Regex patterns for contact data
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX = re.compile(r'\(?\b[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b')
INVALID_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js')

# Social media profile regexes
LINKEDIN_REGEX = re.compile(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
INSTAGRAM_REGEX = re.compile(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
FACEBOOK_REGEX = re.compile(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
TIKTOK_REGEX = re.compile(r'https?://(?:www\.)?tiktok\.com/@[a-zA-Z0-9_\-\.]+/?', re.IGNORECASE)
X_REGEX = re.compile(r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+/?', re.IGNORECASE)




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

    # Tag attributes: data-cfemail
    for tag in soup.find_all(attrs={"data-cfemail": True}):
        try:
            decoded = decode_cf_email(tag["data-cfemail"])
            if decoded and "@" in decoded:
                emails.append(decoded.lower())
        except Exception:
            pass

    # Anchor hrefs: /cdn-cgi/l/email-protection#<hex>
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


def extract_social_links(html_or_text: str) -> dict:
    """Extracts verified social media profiles (LinkedIn, Instagram, Facebook, TikTok, X)."""
    socials = {
        "linkedin": [],
        "instagram": [],
        "facebook": [],
        "tiktok": [],
        "x": []
    }
    ignore_subs = ["/sharer", "/share", "/intent", "/privacy", "/terms", "/home", "/pages", "/login", "/search"]
    
    for match in LINKEDIN_REGEX.findall(html_or_text):
        if not any(sub in match.lower() for sub in ignore_subs) and match not in socials["linkedin"]:
            socials["linkedin"].append(match.rstrip("/"))
            
    for match in INSTAGRAM_REGEX.findall(html_or_text):
        if not any(sub in match.lower() for sub in ignore_subs) and match not in socials["instagram"]:
            socials["instagram"].append(match.rstrip("/"))
            
    for match in FACEBOOK_REGEX.findall(html_or_text):
        if not any(sub in match.lower() for sub in ignore_subs) and match not in socials["facebook"]:
            socials["facebook"].append(match.rstrip("/"))
            
    for match in TIKTOK_REGEX.findall(html_or_text):
        if not any(sub in match.lower() for sub in ignore_subs) and match not in socials["tiktok"]:
            socials["tiktok"].append(match.rstrip("/"))
            
    for match in X_REGEX.findall(html_or_text):
        if not any(sub in match.lower() for sub in ignore_subs) and match not in socials["x"]:
            socials["x"].append(match.rstrip("/"))
            
    return socials


def is_valid_email(email: str) -> bool:
    """Filter out image assets or scripts matching email regex."""
    clean = email.strip().lower()
    return not clean.endswith(INVALID_EXTENSIONS) and "@" in clean


# ---------------------------------------------------------------------------
# 1. 2-Tier Scraping Waterfall (Tier 1 curl_cffi -> Tier 2 Playwright)
# ---------------------------------------------------------------------------

async def fetch_tier1_static(url: str, timeout: int = 10) -> tuple[int, str]:
    """Tier 1: Fast static scrape using curl_cffi Chrome impersonation (or httpx)."""
    if HAS_CURL_CFFI:
        try:
            async with CurlAsyncSession(impersonate="chrome120", timeout=timeout) as session:
                resp = await session.get(url, allow_redirects=True)
                return resp.status_code, resp.text
        except Exception:
            pass

    # Fallback to standard httpx if curl_cffi blocked or unavailable
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }) as client:
            resp = await client.get(url)
            return resp.status_code, resp.text
    except Exception:
        return 0, ""


async def scrape_company_data(base_url: str, p_browser=None) -> dict:
    """Scrapes company base URL and common subpages using a 2-Tier Waterfall:
    - Tier 1: Static Fast-Pass (curl_cffi with chrome120 impersonation + BeautifulSoup)
    - Tier 2: Dynamic Fallback (Playwright) if Tier 1 encounters bot challenge or empty JS shell.
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
    phones = set()
    socials = {"linkedin": [], "instagram": [], "facebook": [], "tiktok": [], "x": []}
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

            # 3. Phones
            for p in PHONE_REGEX.findall(text):
                phones.add(p)

            # 4. Social links
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
                        for p in PHONE_REGEX.findall(text):
                            phones.add(p)

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

    return {
        'emails': sorted(list(emails)),
        'phones': sorted(list(phones)),
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
                                phone = m.group(1).strip()

                    results.append({
                        "company_name": name,
                        "website_url": website,
                        "domain": domain,
                        "phone": phone,
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


async def main():
    query = "packaging distributors munich"
    print(f"Searching Google Maps B2B for: {query}")
    leads = await scrape_google_maps_b2b(query, target_leads=5)
    print(f"Found {len(leads)} leads:")
    for l in leads:
        print(l)

if __name__ == "__main__":
    asyncio.run(main())
