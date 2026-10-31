import sys
import os
import re
import csv
import uuid
import json
import asyncio
import inspect
import unicodedata
from urllib.parse import urlparse
import httpx
import dns.resolver
import dns.asyncresolver
try:
    import phonenumbers
    HAS_PHONENUMBERS = True
except ImportError:
    HAS_PHONENUMBERS = False
from bs4 import BeautifulSoup
from ddgs import DDGS
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from lead_hunter import (
    extract_social_links,
    extract_whatsapp,
    extract_phone_numbers,
    is_valid_phone,
    normalize_social_url,
    search_social_fallback,
    clean_domain,
    scrape_google_maps_b2b,
    save_leads_to_excel_and_csv as hunter_save_leads,
    upsert_lead_to_excel_and_csv as hunter_upsert_lead,
    EXPORT_HEADERS,
)

mcp = FastMCP("LeadDirect")

# ---------------------------------------------------------------------------
# Resilience Middleware: Tolerate Unexpected Kwargs from Small Local LLMs
# ---------------------------------------------------------------------------
class ExtraArgsFilterMiddleware(Middleware):
    """Intercepts tool calls and filters out unexpected keyword arguments
    so small local LLMs never trigger Pydantic 'Unexpected keyword argument' validation crashes.
    """
    def __init__(self, server: FastMCP):
        self.server = server

    async def on_call_tool(self, context, call_next):
        try:
            tool_name = context.message.name
            tool = await self.server.get_tool(tool_name)
            if tool and hasattr(tool, 'fn'):
                sig = inspect.signature(tool.fn)
                allowed_params = set(sig.parameters.keys())
                if context.message.arguments:
                    filtered = {k: v for k, v in context.message.arguments.items() if k in allowed_params}
                    context.message.arguments = filtered
        except Exception:
            pass
        return await call_next(context)

mcp.add_middleware(ExtraArgsFilterMiddleware(mcp))


# ---------------------------------------------------------------------------
# Desktop & Portable Output Directory Handling
# ---------------------------------------------------------------------------
def get_desktop_dir() -> str:
    """Resolves the user's Desktop directory across Windows (including OneDrive), macOS, and Linux."""
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive and os.path.isdir(os.path.join(onedrive, "Desktop")):
        return os.path.join(onedrive, "Desktop")
    std_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(std_desktop):
        return std_desktop
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

DESKTOP_DIR = get_desktop_dir()
OUTPUT_DIR = os.environ.get("LEADDIRECT_OUTPUT_DIR") or os.path.join(DESKTOP_DIR, "LeadDirect_Leads")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CSV_FILE = os.environ.get("LEADDIRECT_CSV_OUTPUT") or os.path.join(OUTPUT_DIR, "leads_output.csv")
EXCEL_FILE = os.environ.get("LEADDIRECT_EXCEL_OUTPUT") or os.path.join(OUTPUT_DIR, "LeadDirect_B2B_Leads.xlsx")

# 12-Column Schema Definition
HEADERS = [
    "Company Name", "Domain", "Email", "Phone", "WhatsApp",
    "Facebook", "Instagram", "LinkedIn", "TikTok", "Address",
    "Category", "Date Added"
]

# ---------------------------------------------------------------------------
# CSV Document Support & Consulting Notice Banner
# ---------------------------------------------------------------------------
CSV_SUPPORT_BANNER = [
    [
        "If LeadDirect-MCP saves your team from monthly SaaS subscriptions or cuts your LLM token spend, consider backing ongoing development. Your support keeps these local AI and OSINT tools free and actively maintained. Support via Patreon: https://www.patreon.com/netizen4_bit"
    ],
    [
        "Need a Custom B2B Automation or Agentic Pipeline? Need a tailored MCP server, private OSINT enrichment module, or autonomous Agentic workflow built specifically for your company? Reach out via Linkdin: https://www.linkedin.com/in/nihatkasim for custom integration and consulting."
    ],
    []
]


def init_csv_file(file_path: str, headers: list[str]) -> None:
    """Initializes CSV file with support and custom pipeline consulting notice followed by headers."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for banner_row in CSV_SUPPORT_BANNER:
            writer.writerow(banner_row)
        writer.writerow(headers)


def get_existing_domains() -> set[str]:
    """Collects already discovered domains from both CSV and Excel to prevent duplicates."""
    domains = set()
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if row and len(row) > 1:
                        col0 = row[0].strip().lower()
                        if not col0.startswith("if leaddirect") and not col0.startswith("need a custom") and not col0.startswith("#") and col0 != "company" and col0 != "company name":
                            d = clean_domain(row[1])
                            if d:
                                domains.add(d)
        except Exception:
            pass

    if os.path.exists(EXCEL_FILE):
        try:
            wb = openpyxl.load_workbook(EXCEL_FILE, read_only=True)
            ws = wb.active
            for row in ws.iter_rows(min_row=5, min_col=2, max_col=2, values_only=True):
                if row and row[0]:
                    d = clean_domain(str(row[0]))
                    if d:
                        domains.add(d)
            wb.close()
        except Exception:
            pass
    return domains


def save_leads_to_excel_and_csv(leads: list[dict]) -> tuple[str, str]:
    """Saves or appends leads to both a formatted Excel (.xlsx) file and a CSV file in OUTPUT_DIR using the 12-column schema."""
    return hunter_upsert_lead(leads, excel_path=EXCEL_FILE, csv_path=CSV_FILE)


def upsert_lead_to_excel_and_csv(lead_data: dict) -> tuple[str, str]:
    """Upserts or merges lead fields into matching Domain row in Excel and CSV."""
    return hunter_upsert_lead(lead_data, excel_path=EXCEL_FILE, csv_path=CSV_FILE)


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
    if HAS_PHONENUMBERS:
        try:
            for match in phonenumbers.PhoneNumberMatcher(text, dynamic_region):
                formatted_num = phonenumbers.format_number(
                    match.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                )
                if is_valid_phone(formatted_num):
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
    """Decode a Cloudflare-obfuscated email."""
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

    for tag in soup.find_all(attrs={"data-cfemail": True}):
        try:
            email = sanitize_email(decode_cf_email(tag["data-cfemail"]))
            if email and "@" in email:
                emails.append(email)
        except (ValueError, IndexError):
            pass

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

    f = first[0]

    patterns = [
        f"{first}.{last}",
        f"{f}.{last}",
        f"{first}",
        f"{last}.{first}",
        f"{f}{last}",
        f"{first}{last}",
    ]
    return [f"{p}@{domain}" for p in patterns]


# ---------------------------------------------------------------------------
# 3. DNS MX Resolver
# ---------------------------------------------------------------------------

async def get_mx_hosts(domain: str) -> list[str]:
    """Resolve MX records for domain, returning hostnames sorted by priority."""
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
    """Perform a zero-bounce SMTP verification against mx_host."""
    domain = email.split("@", 1)[-1]
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25), timeout=5.0
        )
    except Exception:
        return "ERROR"

    try:
        await asyncio.wait_for(reader.read(4096), timeout=5.0)

        code, _ = await _smtp_exchange(reader, writer, "EHLO mail.validation-check.local")
        if code not in (220, 250):
            return "ERROR"

        code, _ = await _smtp_exchange(reader, writer, "MAIL FROM:<check@validation-check.local>")
        if code != 250:
            return "ERROR"

        random_addr = f"test-{uuid.uuid4().hex[:12]}@{domain}"
        code_catchall, _ = await _smtp_exchange(
            reader, writer, f"RCPT TO:<{random_addr}>"
        )
        if code_catchall == 250:
            return "CATCH_ALL"

        await _smtp_exchange(reader, writer, "RSET")
        await _smtp_exchange(reader, writer, "MAIL FROM:<check@validation-check.local>")

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
    """Finds B2B leads using DuckDuckGo, extracts emails, hardened phones, WhatsApp,
    and social media links, and saves/merges to Excel and CSV on Desktop.
    """
    count = _increment_counter()
    existing_domains = get_existing_domains()

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
                domain = clean_domain(url)
            except Exception:
                continue

            if not domain or any(ignored in domain for ignored in ignore_list):
                continue

            if domain in existing_domains:
                continue

            email = "Website Form"
            phone = "Not Found"
            whatsapp = ""
            fb_url = ""
            ig_url = ""
            li_url = ""
            tt_url = ""

            try:
                response = client.get(f"https://{domain}")
                html = response.text

                # 1. Email extraction
                emails = re.findall(
                    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html
                )
                valid_emails = [
                    sanitize_email(e) for e in emails
                    if not e.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp"))
                ]
                valid_emails = [e for e in valid_emails if e and "@" in e]
                cf_e = extract_cf_emails(html)
                for ce in cf_e:
                    if ce and "@" in ce:
                        valid_emails.append(ce)
                if valid_emails:
                    email = valid_emails[0]

                # 2. Hardened Phone Extraction (rejects timestamps)
                found_phones = extract_phone_numbers(html)
                if found_phones:
                    phone = found_phones[0]

                # 3. WhatsApp Extraction
                wa = extract_whatsapp(html)
                if wa:
                    whatsapp = wa

                # 4. Social Links Extraction
                socials = extract_social_links(html)
                if socials.get("facebook"):
                    fb_url = socials["facebook"][0]
                if socials.get("instagram"):
                    ig_url = socials["instagram"][0]
                if socials.get("linkedin"):
                    li_url = socials["linkedin"][0]
                if socials.get("tiktok"):
                    tt_url = socials["tiktok"][0]
                if not whatsapp and socials.get("whatsapp"):
                    whatsapp = socials["whatsapp"][0]

                # 5. Social Search Fallback if missing
                if not fb_url and not ig_url and not li_url and not whatsapp:
                    fallback = search_social_fallback(title, domain)
                    fb_url = fallback.get("facebook", "")
                    ig_url = fallback.get("instagram", "")
                    li_url = fallback.get("linkedin", "")
                    tt_url = fallback.get("tiktok", "")
                    if not whatsapp:
                        whatsapp = fallback.get("whatsapp", "")

            except Exception:
                pass

            found_leads.append({
                "company": title,
                "domain": domain,
                "email": email,
                "phone": phone,
                "whatsapp": whatsapp,
                "facebook": fb_url,
                "instagram": ig_url,
                "linkedin": li_url,
                "tiktok": tt_url,
                "address": "N/A",
                "category": "Distributor / Wholesaler",
                "date_added": str(datetime.date.today())
            })
            existing_domains.add(domain)

            if len(found_leads) >= target_leads:
                break

    if not found_leads:
        return "No new leads found."

    excel_path, csv_path = save_leads_to_excel_and_csv(found_leads)

    md = "| Company | Domain | Email | Phone | WhatsApp | LinkedIn |\n|---|---|---|---|---|---|\n"
    for l in found_leads:
        title = l["company"]
        d = l["domain"]
        em = l["email"]
        ph = l["phone"]
        wa = l["whatsapp"] or "—"
        li = l["linkedin"] or "—"
        md += f"| {title} | {d} | {em} | {ph} | {wa} | {li} |\n"

    md += (
        f"\n\n---\n"
        f"📁 **Results saved to Desktop folder:** `{OUTPUT_DIR}`\n"
        f"* 📊 **Excel Spreadsheet (12 Columns):** `{excel_path}`\n"
        f"* 📄 **CSV Export (12 Columns):** `{csv_path}`"
    )

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
    extracting WhatsApp, phones, and social links, generating executive email permutations,
    performing zero-bounce SMTP validation, and auto-updating/merging LeadDirect_B2B_Leads.xlsx.
    """
    clean_d = clean_domain(domain)
    count = _increment_counter()
    result: dict = {
        "domain": clean_d,
        "mx_hosts": [],
        "scraped_emails": [],
        "cf_decoded_emails": [],
        "phones": [],
        "whatsapp": "",
        "social_profiles": {"linkedin": [], "instagram": [], "facebook": [], "tiktok": [], "x": []},
        "permuted_candidates": [],
        "verified": [],
        "unverified_permutations": [],
        "catch_all_domain": False,
        "excel_updated": EXCEL_FILE,
        "csv_updated": CSV_FILE,
        "status": "ok",
    }

    # Step 1: Check for Marketplace or Resolve MX records
    global_marketplaces = [
        "facebook.com", "instagram.com", "truckscout24.", "machineryzone.",
        "agriaffaires.", "europages.", "autoline."
    ]

    is_marketplace = any(market in clean_d for market in global_marketplaces)

    if is_marketplace:
        target_url = website_url or f"https://{clean_d}"
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

        tld = clean_d.split('.')[-1].upper()
        region_hint = tld if len(tld) == 2 else None

        extracted_data = extract_marketplace_contacts(page_text, dynamic_region=region_hint)
        result["status"] = "marketplace_extracted"
        result["scraped_emails"] = extracted_data["emails"]
        result["phones"] = extracted_data["phones"]
        result["whatsapp"] = extract_whatsapp(page_text)
        result["social_profiles"] = extract_social_links(page_text)

        # Auto-update / Upsert to Excel & CSV
        upsert_data = {
            "domain": clean_d,
            "email": extracted_data["emails"][0] if extracted_data["emails"] else "",
            "phone": extracted_data["phones"][0] if extracted_data["phones"] else "",
            "whatsapp": result["whatsapp"],
            "facebook": result["social_profiles"].get("facebook", [""])[0] if result["social_profiles"].get("facebook") else "",
            "instagram": result["social_profiles"].get("instagram", [""])[0] if result["social_profiles"].get("instagram") else "",
            "linkedin": result["social_profiles"].get("linkedin", [""])[0] if result["social_profiles"].get("linkedin") else "",
            "tiktok": result["social_profiles"].get("tiktok", [""])[0] if result["social_profiles"].get("tiktok") else "",
        }
        upsert_lead_to_excel_and_csv(upsert_data)
        return _maybe_append_support(result, count)

    else:
        mx_hosts = await get_mx_hosts(clean_d)
        result["mx_hosts"] = mx_hosts
        if not mx_hosts:
            result["status"] = "no_mx_records"
            return _maybe_append_support(result, count)

    # Step 2: Scrape website for direct contact emails, phones, whatsapp, socials
    target_url = website_url or f"https://{clean_d}"
    scraped_emails: set[str] = set()
    cf_emails: set[str] = set()
    scraped_phones: list[str] = []
    whatsapp_val = ""

    async with httpx.AsyncClient(
        timeout=8.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    ) as client:
        for path in ("", "/contact", "/contact-us", "/about", "/about-us", "/team"):
            url = f"https://{clean_d}{path}" if path else target_url
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

                # Extract hardened phones
                for p in extract_phone_numbers(html):
                    if p not in scraped_phones:
                        scraped_phones.append(p)

                # Extract WhatsApp
                if not whatsapp_val:
                    wa = extract_whatsapp(html)
                    if wa:
                        whatsapp_val = wa

                found_socials = extract_social_links(html)
                for net, links in found_socials.items():
                    for link in links:
                        if link not in result["social_profiles"][net]:
                            result["social_profiles"][net].append(link)
            except Exception:
                continue

    result["scraped_emails"] = sorted(scraped_emails)
    result["cf_decoded_emails"] = sorted(cf_emails)
    result["phones"] = scraped_phones
    result["whatsapp"] = whatsapp_val

    # Step 3: Generate permutations
    candidates: list[str] = []
    if first_name and last_name:
        candidates = generate_email_permutations(first_name, last_name, clean_d)
        result["permuted_candidates"] = candidates

    # Step 4: Combine all candidate emails
    all_candidates = list(
        dict.fromkeys(
            list(cf_emails) + list(scraped_emails) + candidates
        )
    )

    best_verified_email = ""

    if all_candidates and mx_hosts:
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
                    if not best_verified_email:
                        best_verified_email = sc
                break

            if smtp_result == "VALID" and not best_verified_email:
                best_verified_email = email

            verified.append({"email": email, "smtp_status": smtp_result})

        result["verified"] = verified

    if not best_verified_email and scraped_emails:
        best_verified_email = sorted(list(scraped_emails))[0]
    elif not best_verified_email and cf_emails:
        best_verified_email = sorted(list(cf_emails))[0]

    # Step 5: Auto-Update & Merge existing rows in Excel and CSV
    upsert_data = {
        "domain": clean_d,
        "email": best_verified_email,
        "phone": scraped_phones[0] if scraped_phones else "",
        "whatsapp": whatsapp_val,
        "facebook": result["social_profiles"].get("facebook", [""])[0] if result["social_profiles"].get("facebook") else "",
        "instagram": result["social_profiles"].get("instagram", [""])[0] if result["social_profiles"].get("instagram") else "",
        "linkedin": result["social_profiles"].get("linkedin", [""])[0] if result["social_profiles"].get("linkedin") else "",
        "tiktok": result["social_profiles"].get("tiktok", [""])[0] if result["social_profiles"].get("tiktok") else "",
    }
    upsert_lead_to_excel_and_csv(upsert_data)

    return _maybe_append_support(result, count)


# ---------------------------------------------------------------------------
# 7. OSINT Reconnaissance Tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def osint_recon_domain(domain: str) -> dict:
    """Performs zero-cost OSINT reconnaissance on a B2B domain without paid APIs:
    - Discovers hidden wholesale/B2B subdomains via SSL Certificate Transparency logs (crt.sh).
    - Identifies corporate mail infrastructure (Google Workspace, Microsoft 365, Zoho) via DNS MX/SPF.
    - Extracts Schema.org JSON-LD corporate metadata (legal name, official telephone, social links).
    - Auto-updates & merges discovered contacts, WhatsApp, and social profiles into LeadDirect_B2B_Leads.xlsx.
    """
    clean_d = clean_domain(domain)
    count = _increment_counter()

    recon = {
        "domain": clean_d,
        "subdomains": [],
        "mail_provider": "Unknown",
        "mx_hosts": [],
        "phones": [],
        "whatsapp": "",
        "social_profiles": {"linkedin": [], "instagram": [], "facebook": [], "tiktok": [], "x": []},
        "organization_meta": {
            "legal_name": None,
            "telephone": None,
            "official_email": None,
            "social_links": []
        },
        "excel_updated": EXCEL_FILE,
        "csv_updated": CSV_FILE,
        "status": "ok"
    }

    # 1. SSL Certificate Transparency Subdomain Enumeration (crt.sh)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.get(f"https://crt.sh/?q=%25.{clean_d}&output=json")
            if res.status_code == 200:
                data = res.json()
                discovered = set()
                for entry in data:
                    name_val = entry.get("name_value", "")
                    for sub in name_val.split("\n"):
                        sub = sub.strip().lower()
                        if "*" not in sub and sub.endswith(clean_d) and sub != clean_d:
                            if any(k in sub for k in ["b2b", "wholesale", "distributor", "dealer", "portal", "partner", "shop", "app"]):
                                discovered.add(sub)
                recon["subdomains"] = sorted(list(discovered))[:15]
    except Exception:
        pass

    # 2. DNS MX Provider Fingerprinting
    try:
        mx_hosts = await get_mx_hosts(clean_d)
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

    # 3. Schema.org JSON-LD & OpenGraph Metadata + Phone / WhatsApp Extraction
    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        ) as client:
            for path in ("", "/contact", "/contact-us", "/about", "/about-us"):
                resp = await client.get(f"https://{clean_d}{path}")
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")

                    # Check Schema.org JSON-LD
                    for script in soup.find_all("script", type="application/ld+json"):
                        try:
                            content = json.loads(script.string)
                            if isinstance(content, list):
                                content = content[0]
                            if isinstance(content, dict) and content.get("@type") in ["Organization", "Corporation", "LocalBusiness"]:
                                if not recon["organization_meta"]["legal_name"]:
                                    recon["organization_meta"]["legal_name"] = content.get("name")
                                if not recon["organization_meta"]["telephone"]:
                                    raw_tel = content.get("telephone")
                                    if raw_tel and is_valid_phone(str(raw_tel)):
                                        recon["organization_meta"]["telephone"] = str(raw_tel)
                                if not recon["organization_meta"]["official_email"]:
                                    recon["organization_meta"]["official_email"] = content.get("email")
                        except Exception:
                            continue

                    # Extract Structured Social Profiles
                    found_soc = extract_social_links(resp.text)
                    for net, links in found_soc.items():
                        for link in links:
                            if link not in recon["social_profiles"][net]:
                                recon["social_profiles"][net].append(link)

                    # Extract Hardened Phones
                    for p in extract_phone_numbers(resp.text):
                        if p not in recon["phones"]:
                            recon["phones"].append(p)

                    # Extract WhatsApp
                    if not recon["whatsapp"]:
                        wa = extract_whatsapp(resp.text)
                        if wa:
                            recon["whatsapp"] = wa

            recon["organization_meta"]["social_links"] = [
                url for urls in recon["social_profiles"].values() for url in urls
            ][:10]
    except Exception:
        pass

    # 4. Social Search Fallback if missing
    sp = recon["social_profiles"]
    if not sp["facebook"] and not sp["instagram"] and not sp["linkedin"] and not recon["whatsapp"]:
        c_name = recon["organization_meta"]["legal_name"] or ""
        fallback = search_social_fallback(c_name, clean_d)
        for net, link in fallback.items():
            if link and not sp.get(net):
                sp[net] = [link]
        if fallback.get("whatsapp") and not recon["whatsapp"]:
            recon["whatsapp"] = fallback["whatsapp"]

    # 5. Auto-Update & Merge existing rows in Excel and CSV
    official_tel = recon["organization_meta"]["telephone"] or (recon["phones"][0] if recon["phones"] else "")
    upsert_data = {
        "domain": clean_d,
        "company_name": recon["organization_meta"]["legal_name"] or "",
        "email": recon["organization_meta"]["official_email"] or "",
        "phone": official_tel,
        "whatsapp": recon["whatsapp"],
        "facebook": sp.get("facebook", [""])[0] if sp.get("facebook") else "",
        "instagram": sp.get("instagram", [""])[0] if sp.get("instagram") else "",
        "linkedin": sp.get("linkedin", [""])[0] if sp.get("linkedin") else "",
        "tiktok": sp.get("tiktok", [""])[0] if sp.get("tiktok") else "",
    }
    upsert_lead_to_excel_and_csv(upsert_data)

    return _maybe_append_support(recon, count)


# ---------------------------------------------------------------------------
# 8. Google Maps B2B Lead Generator Tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_google_maps_b2b(query: str, target_leads: int = 10) -> str:
    """Searches Google Maps for local/regional B2B businesses, dealers, physical warehouses,
    extracts: company_name, domain, phone, address, and category, and saves to 12-column Excel and CSV.
    """
    count = _increment_counter()
    leads = await scrape_google_maps_b2b(query, target_leads=target_leads)

    if not leads:
        msg = "No B2B leads found on Google Maps for this query."
        if count % 5 == 0:
            msg += _PATREON_MESSAGE
        return msg

    leads_to_save = [
        {
            "company": lead.get("company_name", ""),
            "domain": lead.get("domain", "") or "",
            "email": "Website Form",
            "phone": lead.get("phone", "") or "Not Found",
            "whatsapp": "",
            "facebook": "",
            "instagram": "",
            "linkedin": "",
            "tiktok": "",
            "address": lead.get("address", "") or "Not Found",
            "category": lead.get("category", "") or "Not Found",
        }
        for lead in leads
    ]
    excel_path, csv_path = save_leads_to_excel_and_csv(leads_to_save)

    md = "| Company Name | Domain | Phone | Address | Category |\n|---|---|---|---|---|\n"
    for lead in leads:
        c_name = lead.get("company_name", "Unknown")
        domain = lead.get("domain") or "Not Found"
        phone = lead.get("phone") or "Not Found"
        addr = lead.get("address") or "Not Found"
        cat = lead.get("category") or "Not Found"
        md += f"| {c_name} | {domain} | {phone} | {addr} | {cat} |\n"

    md += (
        f"\n\n---\n"
        f"📁 **Results saved to Desktop folder:** `{OUTPUT_DIR}`\n"
        f"* 📊 **Excel Spreadsheet (12 Columns):** `{excel_path}`\n"
        f"* 📄 **CSV Export (12 Columns):** `{csv_path}`"
    )

    if count % 5 == 0:
        md += _PATREON_MESSAGE

    return md


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import subprocess

    try:
        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        subprocess.run(
            ["git", "pull"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            timeout=15,
            capture_output=True,
            env=git_env,
        )
    except Exception:
        pass  # Allow offline execution

    mcp.run()
