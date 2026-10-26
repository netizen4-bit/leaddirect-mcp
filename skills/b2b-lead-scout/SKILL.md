---
name: b2b-lead-scout
description: Formulates precision DuckDuckGo search dorks, filters out B2B directory spam, and enforces ICP gatekeeping to minimize LLM token spend. Use when searching for B2B leads, distributors, wholesalers, dealers, or suppliers, or before calling `find_distributors`.
license: MIT
metadata:
  version: "1.1.0"
---

# B2B Lead Scout & Search Optimization

## Role & Purpose
Enforces high-intent query formulation and negative keyword filtering when calling `find_distributors`. Prevents agents from wasting LLM context tokens on news articles, SEO blogs, and directory farms (Clutch, Yelp, ZoomInfo, LinkedIn, Apollo, YellowPages).

## 1. Mandatory Query Dorking Matrix (DuckDuckGo-Optimized)
Never pass plain or vague keywords to `find_distributors` (e.g., `"packaging distributors"`). Because DuckDuckGo drops overly long nested boolean queries, construct compact queries by combining:
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

## 2. Fallback & Zero-Result Recovery
If `find_distributors` returns 0 leads on a niche industry:
1. Broaden the intent anchor to a single term (e.g., `"distributor"` or `"supplier"`).
2. Keep the `-site:` negative filters intact so directories never enter the context window.

## 3. Token Budgeting & Tool Handoff Protocol
1. **Never Ingest Raw Crawl Dumps:** Keep raw webpage HTML and full `output/leads_output.csv` contents out of the LLM context window.
2. **Batch Limit:** Process a maximum of 5 candidate domains per iteration.
3. **ICP Gatekeeping First:** Verify that a discovered domain is an active commercial entity matching the target industry before running enrichment tools.
4. **Handoff to `osint-lead-enrichment`:**
   - If a qualified domain lacks a verified direct email from initial discovery, hand off to the `osint-lead-enrichment` protocol (`osint_recon_domain` -> `enrich_and_verify_contact`).
5. **Summary Output Schema:** Present discovered leads strictly in this compact Markdown table:

| Company Name | Domain | Email Found | Phone | ICP & Verification Status |
|---|---|---|---|---|
