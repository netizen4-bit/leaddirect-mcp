"""
Runner script: calls the find_distributors logic directly with multiple
targeted queries for Canadian agricultural machinery B2B leads.
Outputs results to CSV on the Desktop and prints a summary table.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import csv
import re
from urllib.parse import urlparse

# ── Inline the search logic so we don't import server.py (which has Linux paths) ──
from ddgs import DDGS
import httpx

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
        init_csv_file(CSV_FILE, ["Company", "Domain", "Email", "Phone"])

    # Load already-seen domains
    existing_domains = set()
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and len(row) > 1:
                col0 = row[0].strip().lower()
                if not col0.startswith("if leaddirect") and not col0.startswith("need a custom") and not col0.startswith("#") and col0 != "company":
                    existing_domains.add(row[1].strip().lower())

    all_leads = []

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
                    domain = urlparse(url).netloc.replace("www.", "").strip().lower()
                except Exception:
                    continue

                if not domain or any(ign in domain for ign in IGNORE_LIST):
                    continue
                if domain in existing_domains:
                    continue

                email = "Website Form"
                phone = "Not Found"

                try:
                    resp = client.get(f"https://{domain}")
                    text = resp.text

                    emails = re.findall(
                        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text
                    )
                    valid_emails = [
                        e for e in emails
                        if not e.endswith((".png", ".jpg", ".jpeg", ".svg", ".webp"))
                    ]
                    if valid_emails:
                        email = valid_emails[0]

                    phones = re.findall(
                        r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text
                    )
                    if phones:
                        phone = phones[0]
                except Exception:
                    pass

                lead = (title, domain, email, phone)
                all_leads.append(lead)
                existing_domains.add(domain)
                print(f"  ✅ {title[:50]:50s}  {domain:30s}  {email:35s}  {phone}")

    # ── Write all new leads to the Desktop CSV ──
    if all_leads:
        with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for lead in all_leads:
                writer.writerow(lead)

    # ── Also save a copy in the project output/ dir ──
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "canadian_ag_machinery_leads.csv")
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Company", "Domain", "Email", "Phone"])
        for lead in all_leads:
            writer.writerow(lead)

    # ── Summary ──
    print(f"\n{'='*70}")
    print(f"DONE — {len(all_leads)} unique leads found across {len(QUERIES)} queries")
    print(f"  Desktop CSV : {CSV_FILE}")
    print(f"  Project CSV : {output_path}")
    print('='*70)

    # Print markdown table
    print("\n| # | Company | Domain | Email | Phone |")
    print("|---|---------|--------|-------|-------|")
    for i, (title, domain, email, phone) in enumerate(all_leads, 1):
        print(f"| {i} | {title} | {domain} | {email} | {phone} |")


if __name__ == "__main__":
    run_all_queries()
