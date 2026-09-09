import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
import json
import csv
import os
from urllib.parse import urljoin, urlparse
from ddgs import DDGS
from playwright.async_api import async_playwright
from ollama import AsyncClient

# Regex patterns for contact data
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX = re.compile(r'\(?\b[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b')
INVALID_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js')

ollama_client = AsyncClient(host='http://localhost:11434')

def is_valid_email(email):
    """Filter out image files or assets that match the email regex"""
    return not email.lower().endswith(INVALID_EXTENSIONS)

async def scrape_company_data(base_url, p_browser):
    """Deep scrape the base URL and common contact pages"""
    pages_to_visit = [
        base_url,
        urljoin(base_url, '/contact'),
        urljoin(base_url, '/contact-us'),
        urljoin(base_url, '/about'),
        urljoin(base_url, '/about-us'),
        urljoin(base_url, '/team'),
        urljoin(base_url, '/staff')
    ]
    
    emails = set()
    phones = set()
    raw_text_chunks = []

    # Use a realistic User-Agent to avoid simple bot blocks
    context = await p_browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ignore_https_errors=True
    )
    
    for url in pages_to_visit:
        page = await context.new_page()
        try:
            # Short timeout per page to keep the script moving
            await page.goto(url, timeout=10000, wait_until='domcontentloaded')
            text = await page.evaluate('document.body.innerText')
            
            if text:
                raw_text_chunks.append(text[:1500]) # Keep snippet size manageable
                
                # Extract emails via regex
                found_emails = EMAIL_REGEX.findall(text)
                for e in found_emails:
                    if is_valid_email(e):
                        emails.add(e.lower())
                        
                # Extract phones via regex
                found_phones = PHONE_REGEX.findall(text)
                phones.update(found_phones)
                
        except Exception:
            # Fail silently on timeouts or 404s for subpages
            pass
        finally:
            await page.close()

    await context.close()
    
    return {
        'emails': list(emails),
        'phones': list(phones),
        'raw_text': " ".join(raw_text_chunks)[:4000] # Cap total text length for LLM
    }

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
            options={'temperature': 0.0} # Low temp for deterministic output
        )
        content = response['message']['content'].strip()
        
        # Clean up markdown code blocks if the model still adds them
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
    query = "agricultural precision planting equipment dealers sellers cooperatives Canada"
    print(f"🔍 Searching for: {query}")
    
    try:
        ddgs = DDGS()
        # Limiting to top 5 results for demonstration/speed
        search_results = list(ddgs.text(query, max_results=5)) 
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return

    leads = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        for result in search_results:
            title = result.get('title', 'Unknown')
            url = result.get('href', '')
            
            # Extract clean root domain
            parsed_uri = urlparse(url)
            base_url = f"{parsed_uri.scheme}://{parsed_uri.netloc}/"
            
            print(f"\n🌐 Processing: {title}")
            print(f"   Base URL: {base_url}")
            
            # Deep scrape
            scraped_data = await scrape_company_data(base_url, browser)
            print(f"   Found {len(scraped_data['emails'])} emails and {len(scraped_data['phones'])} phones.")
            
            # Normalize text
            summary, tags = "", ""
            if scraped_data['raw_text']:
                summary, tags = await normalize_with_llm(title, scraped_data['raw_text'])
                if tags:
                    print(f"   Tags: {tags}")
            
            # Append to leads list
            leads.append({
                "Company Name": title,
                "Website URL": base_url,
                "Discovered Emails": ", ".join(scraped_data['emails']),
                "Phone Numbers": ", ".join(scraped_data['phones']),
                "Page Title/Summary": summary,
                "Industry Tags": tags
            })
            
        await browser.close()
        
    # Compile directly into CSV using Python's built-in csv module
    file_name = "canadian_agri_leads.csv"
    with open(file_name, mode='w', newline='', encoding='utf-8') as f:
        fieldnames = ["Company Name", "Website URL", "Discovered Emails", "Phone Numbers", "Page Title/Summary", "Industry Tags"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)
        
    cwd = os.getcwd()
    summary_string = f"\nSuccessfully scraped {len(leads)} agricultural dealers in Canada. Detailed contact information has been saved locally to {file_name}.\nExact directory path: {cwd}"
    print(summary_string)
    
    return summary_string

if __name__ == "__main__":
    asyncio.run(main())
