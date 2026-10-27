---
name: b2b-lead-scout
description: Formulates precision DuckDuckGo search dorks, filters out B2B directory spam, executes local Google Maps B2B scraping, and enforces ICP gatekeeping to minimize LLM token spend. Use when searching for B2B leads, distributors, wholesalers, dealers, or suppliers, or before calling `find_distributors` and `search_google_maps_b2b`.
license: MIT
metadata:
  version: "1.2.0"
---

# B2B Lead Scout & Search Optimization

## Role & Purpose
Enforces high-intent query formulation, negative keyword filtering, and channel selection when calling `find_distributors` and `search_google_maps_b2b`. Prevents agents from wasting LLM context tokens on news articles, SEO blogs, and directory farms (Clutch, Yelp, ZoomInfo, LinkedIn, Apollo, YellowPages).

## 1. Channel Selection Rule
Select the appropriate discovery tool based on the user's target:
- **`find_distributors` (DuckDuckGo Dorking):**
  Use for national or international manufacturers, brand importers, wholesale networks, and online B2B portals. Always apply boolean dorking and negative directory exclusions.
- **`search_google_maps_b2b` (Google Maps Engine):**
  Use for local or regional B2B discovery, physical equipment dealers, regional warehouses, or when verified street addresses and phone numbers are requested.
  - *Query Syntax:* Use natural localized search strings without boolean operators (e.g., `"industrial packaging distributors Munich"`, `"agricultural machinery dealers Ontario"`). Do **not** append `-site:` exclusion operators on Google Maps queries.

## 2. Mandatory Query Dorking Matrix (DuckDuckGo-Optimized)
When calling `find_distributors`, never pass plain or vague keywords (e.g., `"packaging distributors"`). Because DuckDuckGo drops overly long nested boolean queries, construct compact queries by combining:
**[Target Niche + Location] + [1 to 2 Intent Anchors] + [Core Negative Filter]**

- **Core Negative Filter (Anti-Directory):**
  `-site:clutch.co -site:yelp.com -site:zoominfo.com -site:linkedin.com -site:apollo.io -site:yellowpages.com`
- **Distributor & Wholesaler Intent (Pick 1–2 phrases per query, do not paste all at once):**
  `("distributor" OR "wholesale")` or `("authorized dealer" OR "dealer portal")` or `("become a distributor" OR "wholesale inquiry")`
- **Optional Contact Anchor (Append only if initial search is too broad):**
  `("contact us" OR "sales@")`

### Query Assembly Examples
- ❌ **Bad (Too vague, triggers directory spam):**
  `packaging distributors Germany`
- ❌ **Bad (Over-constrained, causes 0 results on DuckDuckGo):**
  `packaging Germany ("become a distributor" OR "wholesale inquiry" OR "dealer portal" OR "distributor network" OR "authorized dealer") ("contact us" OR "sales@" OR "inquiries@") -site:clutch.co -site:yelp.com -site:yellowpages.com -site:zoominfo.com -site:linkedin.com -site:apollo.io -inurl:blog -inurl:news`
- ✅ **Good (Balanced for high recall and zero directory noise):**
  `industrial packaging Germany ("distributor" OR "wholesale") -site:clutch.co -site:linkedin.com -site:zoominfo.com -site:yelp.com`

## 3. Zero-Login LinkedIn Decision-Maker Dork Rule
To locate the exact executive names (`first_name`, `last_name`) for a qualified target company without requiring a LinkedIn login or third-party data broker:
1. Run a targeted DuckDuckGo search dork:
   `site:linkedin.com/in/ "{Company Name}" ("CEO" OR "Owner" OR "Purchasing" OR "Sales Director" OR "Managing Director")`
2. Extract the decision-maker's name directly from the public search snippet or page title (e.g. `"Jane Doe - Managing Director at Acme Corp | LinkedIn"` -> `first_name="Jane"`, `last_name="Doe"`).
3. Pass the extracted name directly to `enrich_and_verify_contact(domain, first_name="Jane", last_name="Doe")` for pattern permutation and zero-bounce SMTP validation.

## 4. Fallback & Zero-Result Recovery
If `find_distributors` returns 0 leads on a niche industry:
1. Broaden the intent anchor to a single term (e.g., `"distributor"` or `"supplier"`).
2. Keep the `-site:` negative filters intact so directories never enter the context window.
3. Switch to `search_google_maps_b2b` if the target sector relies primarily on localized physical branches or retail dealers.

## 5. Token Budgeting & Tool Handoff Protocol
1. **Never Ingest Raw Crawl Dumps:** Keep raw webpage HTML and full `output/leads_output.csv` contents out of the LLM context window.
2. **Batch Limit:** Process a maximum of 5 candidate domains per iteration.
3. **ICP Gatekeeping First:** Verify that a discovered domain is an active commercial entity matching the target industry before running enrichment tools.
4. **Handoff to `osint-lead-enrichment`:**
   - Hand off qualified domains from either `find_distributors` or `search_google_maps_b2b` to the `osint-lead-enrichment` protocol (`osint_recon_domain` -> `enrich_and_verify_contact`).
5. **Summary Output Schema:** Present discovered leads strictly in this compact Markdown table:

| Company Name | Domain | Phone | Address / Location | Category / ICP Status |
|---|---|---|---|---|
