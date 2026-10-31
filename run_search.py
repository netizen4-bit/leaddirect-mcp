"""
Runner script: calls the find_distributors logic directly with multiple
targeted queries for Canadian agricultural machinery B2B leads.
Outputs results to 12-column CSV and Excel on the Desktop and prints a summary table.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import csv
import re
import datetime
from urllib.parse import urlparse
from ddgs import DDGS
import httpx

from lead_hunter import (
    is_valid_phone,
    extract_phone_numbers,
    extract_whatsapp,
    extract_social_links,
    search_social_fallback,
    clean_domain,
    save_leads_to_excel_and_csv,
    upsert_lead_to_excel_and_csv,
    EXPORT_HEADERS,
)


def get_desktop_dir() -> str:
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive and os.path.isdir(os.path.join(onedrive, "Desktop")):
        return os.path.join(onedrive, "Desktop")
    std = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(std):
        return std
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

OUTPUT_DIR = os.environ.get("LEADDIRECT_OUTPUT_DIR") or os.path.join(get_desktop_dir(), "LeadDirect_Leads")
os.makedirs(OUTPUT_DIR, exist_ok=True)
CSV_FILE = os.environ.get("LEADDIRECT_CSV_OUTPUT") or os.path.join(OUTPUT_DIR, "leads_output.csv")
EXCEL_FILE = os.environ.get("LEADDIRECT_EXCEL_OUTPUT") or os.path.join(OUTPUT_DIR, "LeadDirect_B2B_Leads.xlsx")

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

QUERIES = [
    # Core product queries
    'agricultural machinery distributor dealer Canada tillers cultivators rotovators',
    'farm equipment dealer Canada rotary tiller cultivator wholesale B2B',
    'precision agriculture equipment distributor Canada tillage implements',
    'tractor implements dealer Canada PTO tiller rotovator supplier',
    'Canadian farm machinery distributor prairie provinces tillage equipment',
    # Regional queries
    'agricultural equipment dealer Ontario Quebec tiller cultivator',
    'farm equipment supplier Alberta Saskatchewan Manitoba tillage',
    # Brand / product specific
    'rotovator distributor Canada wholesale farm equipment',
    'power harrow cultivator dealer Canada agricultural',
    'soil preparation equipment dealer Canada B2B wholesale',
]

IGNORE_LIST = [
    "linkedin.com", "facebook.com", "yellowpages", "agdealer.com",
    "kijiji.ca", "youtube.com", "instagram.com", "twitter.com",
    "wikipedia.org", "reddit.com", "amazon.ca", "amazon.com",
    "ebay.com", "ebay.ca", "pinterest.com", "tiktok.com",
    "google.com", "yelp.com", "bbb.org",
]


def run_all_queries():
    # Ensure CSV header and support banner exist
    if not os.path.exists(CSV_FILE):
        init_csv_file(CSV_FILE, EXPORT_HEADERS)

    # Load already-seen domains
    existing_domains = set()
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and len(row) > 1:
                    col0 = row[0].strip().lower()
                    if not col0.startswith("if leaddirect") and not col0.startswith("need a custom") and not col0.startswith("#") and col0 != "company" and col0 != "company name":
                        d = clean_domain(row[1])
                        if d:
                            existing_domains.add(d)

    all_leads = []
    today_str = str(datetime.date.today())

    with httpx.Client(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    ) as client:

        for qi, query in enumerate(QUERIES, 1):
            print(f"\n{'='*70}")
            print(f"[Query {qi}/{len(QUERIES)}] {query}")
            print('='*70)

            try:
                results = list(DDGS().text(query, max_results=40))
            except Exception as e:
                print(f"  ⚠ Search error: {e}")
                continue

            for r in results:
                url = r.get("href", "")
                title = r.get("title", "Unknown")

                try:
                    domain = clean_domain(url)
                except Exception:
                    continue

                if not domain or any(ign in domain for ign in IGNORE_LIST):
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
                    resp = client.get(f"https://{domain}")
                    html = resp.text

                    # Emails
                    emails = re.findall(
                        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html
                    )
                    valid_emails = [
                        e for e in emails
                        if not e.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp"))
                    ]
                    if valid_emails:
                        email = valid_emails[0]

                    # Phones (validated, no timestamps)
                    found_phones = extract_phone_numbers(html)
                    if found_phones:
                        phone = found_phones[0]

                    # WhatsApp
                    wa = extract_whatsapp(html)
                    if wa:
                        whatsapp = wa

                    # Socials
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

                    # Fallback if socials missing
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

                lead = {
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
                    "date_added": today_str
                }
                all_leads.append(lead)
                existing_domains.add(domain)
                print(f"  ✅ {title[:40]:40s}  {domain:25s}  {email:25s}  {phone:18s}  {whatsapp}")

    # ── Write all new leads to Desktop Excel and CSV ──
    if all_leads:
        excel_path, csv_path = save_leads_to_excel_and_csv(all_leads, EXCEL_FILE, CSV_FILE)

        # Also save a copy in the project output/ dir
        output_path = os.path.join(OUTPUT_DIR, "canadian_ag_machinery_leads.csv")
        save_leads_to_excel_and_csv(all_leads, csv_file=output_path)

        print(f"\n{'='*70}")
        print(f"DONE — {len(all_leads)} unique leads found across {len(QUERIES)} queries")
        print(f"  Desktop Excel: {excel_path}")
        print(f"  Desktop CSV  : {csv_path}")
        print(f"  Project CSV  : {output_path}")
        print('='*70)

        # Print markdown table
        print("\n| # | Company | Domain | Email | Phone | WhatsApp | LinkedIn |")
        print("|---|---------|--------|-------|-------|----------|----------|")
        for i, lead in enumerate(all_leads, 1):
            c = lead["company"]
            d = lead["domain"]
            e = lead["email"]
            p = lead["phone"]
            w = lead["whatsapp"] or "—"
            l = lead["linkedin"] or "—"
            print(f"| {i} | {c} | {d} | {e} | {p} | {w} | {l} |")


if __name__ == "__main__":
    run_all_queries()
