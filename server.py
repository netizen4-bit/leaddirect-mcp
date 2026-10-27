import sys
import os
import re
import csv
import uuid
import json
import asyncio
import unicodedata
from urllib.parse import urlparse
import httpx
import dns.resolver
import dns.asyncresolver
import phonenumbers
from bs4 import BeautifulSoup
from ddgs import DDGS
from fastmcp import FastMCP

mcp = FastMCP("LeadDirect")

# Portable output directory handling
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
CSV_FILE = os.environ.get("LEADDIRECT_CSV_OUTPUT") or os.path.join(OUTPUT_DIR, "leads_output.csv")

# ---------------------------------------------------------------------------
# Usage counter & support message
# ---------------------------------------------------------------------------
_tool_execution_count = 0
_PATREON_MESSAGE = (
    "\n\n---\n"
    "I hope you enjoy using this tool. Please show your support for my "
    "further research and development project via patreon: "
    "[https://www.patreon.com/netizen4_bit](https://www.patreon.com/netizen4_bit)"
)


def _increment_counter():
    """Increment the global tool execution counter and return the new value."""
    global _tool_execution_count
    _tool_execution_count += 1
    return _tool_execution_count


def _maybe_append_support(res: dict, count: int) -> dict:
    """Appends support reminder every 5 tool executions."""
    if count % 5 == 0:
        res["support_message"] = (
            "I hope you enjoy using this tool. Please show your support for my "
            "further research and development project via patreon: "
            "[https://www.patreon.com/netizen4_bit](https://www.patreon.com/netizen4_bit)"
        )
    return res


def sanitize_email(e: str) -> str:
    """Strips HTML artifacts, brackets, and unicode escape sequences from emails."""
    if not e:
        return ""
    cleaned = re.sub(r"^(u003e|[<>'\"]|mailto:)", "", e, flags=re.IGNORECASE)
    cleaned = re.sub(r"[<>'\"]$", "", cleaned).strip().lower()
    return cleaned


def extract_marketplace_contacts(text: str, dynamic_region: str = None) -> dict:
    """Scans raw text for emails and global phone numbers."""
    email_pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    raw_emails = re.findall(email_pattern, text)
    valid_emails = [
        sanitize_email(e) for e in raw_emails
        if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'))
    ]
    valid_emails = [e for e in valid_emails if e and "@" in e]
    
    phones = []
    try:
        for match in phonenumbers.PhoneNumberMatcher(text, dynamic_region):
            formatted_num = phonenumbers.format_number(
                match.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
            phones.append(formatted_num)
    except Exception:
        pass
        
    return {
        "emails": sorted(list(set(valid_emails))),
        "phones": sorted(list(set(phones)))
    }


# ---------------------------------------------------------------------------
# 1. Cloudflare XOR De-obfuscator
# ---------------------------------------------------------------------------

def decode_cf_email(encoded_string: str) -> str:
    """Decode a Cloudflare-obfuscated email.
    The first two hex characters are the XOR key; every subsequent pair of hex
    characters is XOR'd against the key to reveal the original character.
    """
    key = int(encoded_string[:2], 16)
    decoded = []
    for i in range(2, len(encoded_string), 2):
        char_code = int(encoded_string[i : i + 2], 16) ^ key
        decoded.append(chr(char_code))
    return "".join(decoded)


def extract_cf_emails(html: str) -> list[str]:
    """Find all Cloudflare-protected emails in an HTML document."""
    soup = BeautifulSoup(html, "html.parser")
    emails: list[str] = []

    # Method 1: data-cfemail attribute on any tag
    for tag in soup.find_all(attrs={"data-cfemail": True}):
        try:
            email = sanitize_email(decode_cf_email(tag["data-cfemail"]))
            if email and "@" in email:
                emails.append(email)
        except (ValueError, IndexError):
            pass

    # Method 2: /cdn-cgi/l/email-protection#<hex> links
    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag["href"]
        if "/cdn-cgi/l/email-protection#" in href:
            hex_part = href.split("#", 1)[-1]
            try:
                email = sanitize_email(decode_cf_email(hex_part))
                if email and "@" in email:
                    emails.append(email)
            except (ValueError, IndexError):
                pass

    return emails


# ---------------------------------------------------------------------------
# 2. Pattern Permutation Engine
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Lowercase, strip diacritics/accents, remove non-alphanumeric chars."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", ascii_only.lower())


def generate_email_permutations(
    first_name: str, last_name: str, domain: str
) -> list[str]:
    """Generate standard corporate email permutations for a person."""
    first = _normalize(first_name)
    last = _normalize(last_name)
    if not first or not last:
        return []

    f = first[0]  # first initial

    patterns = [
        f"{first}.{last}",   # jane.doe
        f"{f}.{last}",       # j.doe
        f"{first}",          # jane
        f"{last}.{first}",   # doe.jane
        f"{f}{last}",        # jdoe
        f"{first}{last}",    # janedoe
    ]
    return [f"{p}@{domain}" for p in patterns]


# ---------------------------------------------------------------------------
# 3. DNS MX Resolver
# ---------------------------------------------------------------------------

async def get_mx_hosts(domain: str) -> list[str]:
    """Resolve MX records for *domain*, returning hostnames sorted by priority."""
    try:
        answers = await dns.asyncresolver.resolve(domain, "MX")
        records = sorted(answers, key=lambda r: r.preference)
        return [str(r.exchange).rstrip(".") for r in records]
    except (
        dns.resolver.NoAnswer,
        dns.resolver.NXDOMAIN,
        dns.resolver.NoNameservers,
        dns.resolver.LifetimeTimeout,
        Exception,
    ):
        return []


# ---------------------------------------------------------------------------
# 4. Zero-Bounce Async SMTP Verifier
# ---------------------------------------------------------------------------

async def _smtp_exchange(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, command: str
) -> tuple[int, str]:
    """Send an SMTP command and return (status_code, full_response)."""
    writer.write((command + "\r\n").encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
    text = response.decode(errors="replace")
    try:
        code = int(text[:3])
    except (ValueError, IndexError):
        code = 0
    return code, text


async def verify_email_smtp(email: str, mx_host: str) -> str:
    """Perform a zero-bounce SMTP verification against *mx_host*.
    Returns one of:
        "VALID"       -> 250 on RCPT TO
        "INVALID"     -> 550/551/553 on RCPT TO
        "CATCH_ALL"   -> server accepts a random UUID probe
        "GREYLISTED"  -> 4xx temporary response
        "ERROR"       -> connection or protocol failure
    """
    domain = email.split("@", 1)[-1]
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25), timeout=5.0
        )
    except Exception:
        return "ERROR"

    try:
        # Read banner
        await asyncio.wait_for(reader.read(4096), timeout=5.0)

        # EHLO
        code, _ = await _smtp_exchange(reader, writer, "EHLO mail.validation-check.local")
        if code not in (220, 250):
            return "ERROR"

        # MAIL FROM
        code, _ = await _smtp_exchange(reader, writer, "MAIL FROM:<check@validation-check.local>")
        if code != 250:
            return "ERROR"

        # Catch-all probe: random UUID address
        random_addr = f"test-{uuid.uuid4().hex[:12]}@{domain}"
        code_catchall, _ = await _smtp_exchange(
            reader, writer, f"RCPT TO:<{random_addr}>"
        )
        if code_catchall == 250:
            return "CATCH_ALL"

        # Reset for real check
        await _smtp_exchange(reader, writer, "RSET")
        await _smtp_exchange(reader, writer, "MAIL FROM:<check@validation-check.local>")

        # RCPT TO with real candidate
        code, _ = await _smtp_exchange(reader, writer, f"RCPT TO:<{email}>")
        if code == 250:
            return "VALID"
        elif code in (550, 551, 553):
            return "INVALID"
        elif 400 <= code < 500:
            return "GREYLISTED"
        else:
            return "ERROR"
    except Exception:
        return "ERROR"
    finally:
        try:
            writer.write(b"QUIT\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 5. Core Discovery Tool
# ---------------------------------------------------------------------------

@mcp.tool()
def find_distributors(query: str, target_leads: int = 10) -> str:
    """Finds B2B leads using DuckDuckGo, extracts emails/phones, and saves to CSV."""
    count = _increment_counter()
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(["Company", "Domain", "Email", "Phone"])

    existing_domains = set()
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) > 1:
                    existing_domains.add(row[1].strip().lower())

    try:
        results = list(DDGS().text(query, max_results=60))
    except Exception as e:
        return f"Search error: {e}"

    ignore_list = [
        "linkedin.com", "facebook.com", "yellowpages", "agdealer.com",
        "kijiji.ca", "youtube.com", "instagram.com", "twitter.com",
        "wikipedia.org", "clutch.co", "yelp.com", "zoominfo.com",
        "apollo.io", "crunchbase.com", "glassdoor.com", "indeed.com"
    ]
    found_leads = []

    with httpx.Client(
        timeout=8.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    ) as client:
        for r in results:
            url = r.get("href", "")
            title = r.get("title", "Unknown")

            try:
                domain = urlparse(url).netloc.replace("www.", "").strip().lower()
            except Exception:
                continue

            if not domain or any(ignored in domain for ignored in ignore_list):
                continue

            if domain in existing_domains:
                continue

            email = "Website Form"
            phone = "Not Found"

            try:
                response = client.get(f"https://{domain}")
                text = response.text

                emails = re.findall(
                    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text
                )
                valid_emails = [
                    sanitize_email(e) for e in emails
                    if not e.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp"))
                ]
                valid_emails = [e for e in valid_emails if e and "@" in e]
                if valid_emails:
                    email = valid_emails[0]

                phones = re.findall(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
                if phones:
                    phone = phones[0]
            except Exception:
                pass

            found_leads.append((title, domain, email, phone))
            existing_domains.add(domain)

            if len(found_leads) >= target_leads:
                break

    if not found_leads:
        return "No new leads found."

    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for lead in found_leads:
            writer.writerow(lead)

    md = "| Company | Domain | Email | Phone |\n|---|---|---|---|\n"
    for title, domain, email, phone in found_leads:
        md += f"| {title} | {domain} | {email} | {phone} |\n"

    if count % 5 == 0:
        md += _PATREON_MESSAGE

    return md


# ---------------------------------------------------------------------------
# 6. Async Enrichment & Verification Tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def enrich_and_verify_contact(
    domain: str,
    first_name: str | None = None,
    last_name: str | None = None,
    website_url: str | None = None,
) -> dict:
    """Enriches a target B2B lead by checking the domain website for obfuscated emails,
    generating pattern permutations for the given executive, and performing zero-bounce
    SMTP validation to identify active direct emails.
    """
    clean_domain = domain.replace("https://", "").replace("http://", "").strip("/").split("/")[0].lower()
    count = _increment_counter()
    result: dict = {
        "domain": clean_domain,
        "mx_hosts": [],
        "scraped_emails": [],
        "cf_decoded_emails": [],
        "permuted_candidates": [],
        "verified": [],
        "unverified_permutations": [],
        "catch_all_domain": False,
        "status": "ok",
    }

    # Step 1: Check for Marketplace or Resolve MX records
    global_marketplaces = [
        "facebook.com", "instagram.com", "truckscout24.", "machineryzone.",
        "agriaffaires.", "europages.", "autoline."
    ]
    
    is_marketplace = any(market in clean_domain for market in global_marketplaces)
    
    if is_marketplace:
        target_url = website_url or f"https://{clean_domain}"
        page_text = ""
        
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            ) as client:
                resp = await client.get(target_url)
                page_text = resp.text
        except Exception:
            page_text = ""

        tld = clean_domain.split('.')[-1].upper()
        region_hint = tld if len(tld) == 2 else None

        extracted_data = extract_marketplace_contacts(page_text, dynamic_region=region_hint)
        result["status"] = "marketplace_extracted"
        result["scraped_emails"] = extracted_data["emails"]
        result["phones"] = extracted_data["phones"]
        return _maybe_append_support(result, count)
        
    else:
        mx_hosts = await get_mx_hosts(clean_domain)
        result["mx_hosts"] = mx_hosts
        if not mx_hosts:
            result["status"] = "no_mx_records"
            return _maybe_append_support(result, count)

    # Step 2: Scrape website for direct contact emails
    target_url = website_url or f"https://{clean_domain}"
    scraped_emails: set[str] = set()
    cf_emails: set[str] = set()

    async with httpx.AsyncClient(
        timeout=8.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    ) as client:
        for path in ("", "/contact", "/about", "/team"):
            url = f"https://{clean_domain}{path}" if path else target_url
            try:
                resp = await client.get(url)
                html = resp.text

                raw = re.findall(
                    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html
                )
                for e in raw:
                    sanitized = sanitize_email(e)
                    if sanitized and not sanitized.endswith((".png", ".jpg", ".jpeg", ".svg", ".webp")):
                        scraped_emails.add(sanitized)

                for e in extract_cf_emails(html):
                    sanitized = sanitize_email(e)
                    if sanitized:
                        cf_emails.add(sanitized)
            except Exception:
                continue

    result["scraped_emails"] = sorted(scraped_emails)
    result["cf_decoded_emails"] = sorted(cf_emails)

    # Step 3: Generate permutations
    candidates: list[str] = []
    if first_name and last_name:
        candidates = generate_email_permutations(first_name, last_name, clean_domain)
        result["permuted_candidates"] = candidates

    # Step 4: Combine all candidate emails
    all_candidates = list(
        dict.fromkeys(
            list(cf_emails) + list(scraped_emails) + candidates
        )
    )

    if not all_candidates:
        result["status"] = "no_email_candidates_found"
        return _maybe_append_support(result, count)

    # Step 5: Zero-Bounce SMTP verification
    primary_mx = mx_hosts[0]
    verified: list[dict] = []

    for email in all_candidates:
        smtp_result = await verify_email_smtp(email, primary_mx)

        if smtp_result == "CATCH_ALL":
            result["catch_all_domain"] = True
            result["status"] = "catch_all_domain"
            result["unverified_permutations"] = all_candidates
            for sc in scraped_emails:
                verified.append({"email": sc, "smtp_status": "SCRAPED_VERIFIED_CATCHALL"})
            break

        verified.append({"email": email, "smtp_status": smtp_result})

    result["verified"] = verified
    return _maybe_append_support(result, count)


# ---------------------------------------------------------------------------
# 7. NEW - Advanced Zero-Cost OSINT Reconnaissance Tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def osint_recon_domain(domain: str) -> dict:
    """Performs zero-cost OSINT reconnaissance on a B2B domain without paid APIs:
    - Discovers hidden wholesale/B2B subdomains via SSL Certificate Transparency logs (crt.sh).
    - Identifies corporate mail infrastructure (Google Workspace, Microsoft 365, Zoho) via DNS MX/SPF.
    - Extracts Schema.org JSON-LD corporate metadata (legal name, official telephone, social links).
    """
    clean_domain = domain.replace("https://", "").replace("http://", "").strip("/").split("/")[0].lower()
    count = _increment_counter()
    
    recon = {
        "domain": clean_domain,
        "subdomains": [],
        "mail_provider": "Unknown",
        "mx_hosts": [],
        "organization_meta": {
            "legal_name": None,
            "telephone": None,
            "official_email": None,
            "social_links": []
        },
        "status": "ok"
    }

    # 1. SSL Certificate Transparency Subdomain Enumeration (crt.sh)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.get(f"https://crt.sh/?q=%25.{clean_domain}&output=json")
            if res.status_code == 200:
                data = res.json()
                discovered = set()
                for entry in data:
                    name_val = entry.get("name_value", "")
                    for sub in name_val.split("\n"):
                        sub = sub.strip().lower()
                        if "*" not in sub and sub.endswith(clean_domain) and sub != clean_domain:
                            # Highlight B2B, wholesale, dealer, partner, or portal subdomains
                            if any(k in sub for k in ["b2b", "wholesale", "distributor", "dealer", "portal", "partner", "shop", "app"]):
                                discovered.add(sub)
                recon["subdomains"] = sorted(list(discovered))[:15]
    except Exception:
        pass

    # 2. DNS MX Provider Fingerprinting
    try:
        mx_hosts = await get_mx_hosts(clean_domain)
        recon["mx_hosts"] = mx_hosts
        mx_joined = " ".join(mx_hosts).lower()
        if "google" in mx_joined or "aspmx" in mx_joined:
            recon["mail_provider"] = "Google Workspace"
        elif "outlook" in mx_joined or "protection" in mx_joined:
            recon["mail_provider"] = "Microsoft 365"
        elif "zoho" in mx_joined:
            recon["mail_provider"] = "Zoho Mail"
        elif "proton" in mx_joined:
            recon["mail_provider"] = "Proton Mail"
        elif mx_hosts:
            recon["mail_provider"] = "Custom / Self-Hosted SMTP"
    except Exception:
        pass

    # 3. Schema.org JSON-LD & OpenGraph Metadata
    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        ) as client:
            resp = await client.get(f"https://{clean_domain}")
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # Check Schema.org JSON-LD
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        content = json.loads(script.string)
                        if isinstance(content, list):
                            content = content[0]
                        if isinstance(content, dict) and content.get("@type") in ["Organization", "Corporation", "LocalBusiness"]:
                            recon["organization_meta"]["legal_name"] = content.get("name")
                            recon["organization_meta"]["telephone"] = content.get("telephone")
                            recon["organization_meta"]["official_email"] = content.get("email")
                    except Exception:
                        continue
                
                # Extract Verified Social Profile Links
                socials = set()
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if any(s in href.lower() for s in ["linkedin.com/company", "twitter.com/", "facebook.com/", "instagram.com/"]):
                        socials.add(href)
                recon["organization_meta"]["social_links"] = sorted(list(socials))[:6]
    except Exception:
        pass

    return _maybe_append_support(recon, count)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import subprocess

    try:
        subprocess.run(
            ["git", "pull"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            timeout=15,
            capture_output=True,
        )
    except Exception:
        pass  # Allow offline execution

    mcp.run()
