---
name: osint-lead-enrichment
description: Executes corporate OSINT enrichment using SSL Certificate Transparency subdomains (crt.sh), DNS MX mail fingerprinting, Schema.org extraction, social profile discovery, and zero-bounce SMTP verification. Use when enriching a domain gathered from find_distributors or search_google_maps_b2b.
license: MIT
metadata:
  version: "1.2.0"
---

# OSINT Lead Enrichment Protocol

## Role & Purpose
Orchestrates multi-layer corporate intelligence by chaining `osint_recon_domain` outputs directly into `enrich_and_verify_contact` inputs for domains gathered from either `find_distributors` or `search_google_maps_b2b`. Uncovers hidden B2B gateways, captures official social media profiles, and verifies direct corporate emails with zero paid API subscriptions and minimal token spend.

## 1. Reconnaissance Waterfall (Strict Execution Order)

### Step 1: Execute `osint_recon_domain(domain)` First
Always run passive OSINT reconnaissance on the root domain before attempting deep contact scraping or SMTP permutation:
- **Subdomain Routing (`crt.sh`):** Inspect discovered SSL Certificate Transparency subdomains for B2B portals (`wholesale.domain.com`, `b2b.domain.com`, `dealers.domain.com`, `portal.domain.com`).
  - *Action Rule:* If an active B2B or dealer subdomain is returned, pass that URL as the `website_url` argument when calling `enrich_and_verify_contact` in Step 2.
- **Mail Provider Fingerprinting (DNS MX):** Use the detected MX provider to evaluate email permutation confidence:
  - **Google Workspace (`aspmx.l.google.com`):** High confidence in `{first}@{domain}` and `{first}.{last}@{domain}`.
  - **Microsoft 365 (`mail.protection.outlook.com`):** High confidence in `{first}.{last}@{domain}` and `{f}{last}@{domain}`.
  - **Zoho / Self-Hosted SMTP:** Elevated catch-all likelihood; prioritize scraped website addresses over guessed permutations.
- **Schema.org JSON-LD & Social Profiles:** Record the official legal entity name, direct telephone number, and social media URLs (LinkedIn, Instagram, Facebook, TikTok, X). If verified direct contact points are already present in Schema.org data, skip redundant page scraping.

### Step 2: Execute `enrich_and_verify_contact(domain, first_name, last_name, website_url)`
- **Executive Name Input:**
  - *Action Rule:* Pass `first_name` and `last_name` when found via public metadata or the LinkedIn Decision-Maker Dork (`site:linkedin.com/in/ "{Company Name}"`). If no executive name is known, omit `first_name` and `last_name` so the tool automatically scrapes `/contact`, `/about`, and `/team` and decodes Cloudflare `data-cfemail` strings directly.
- **Social Media Link Extraction:**
  - Review `result["social_profiles"]` to collect official company profiles on LinkedIn, Instagram, Facebook, TikTok, and X.
- **Catch-All Bounce Defense (`catch_all_domain: true`):**
  - *Action Rule:* If the tool reports `catch_all_domain: true`, discard unverified executive permutations and output only emails explicitly scraped from the website or Schema.org metadata to prevent bounce traps.

## 2. Token Hygiene & Output Schema
Never dump raw JSON responses from `osint_recon_domain` or `enrich_and_verify_contact` into the chat history. Summarize enriched intelligence in this compact Markdown table:

| Legal Company Name | Domain / B2B Subdomain | Mail Provider (MX) | Verified Email | Phone | Social Profiles | Catch-All / Status |
|---|---|---|---|---|---|---|
