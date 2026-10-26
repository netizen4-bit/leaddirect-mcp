---
name: b2b-lead-scout
description: Formulates precision search dorks, filters out aggregator and directory spam, and enforces ICP gatekeeping to minimize LLM token spend.
version: 1.0.0
---

# B2B Lead Scout & Search Optimization

## Role & Purpose
Enforces high-intent query formulation and negative keyword filtering when using `find_distributors`. Prevents agents from wasting LLM tokens on non-relevant links, news articles, and directory farms (Clutch, Yelp, ZoomInfo, LinkedIn).

## 1. Mandatory Query Dorking Matrix
Never pass plain or vague keywords to `find_distributors` (e.g., "packaging distributors"). Always augment search strings with intent anchors and exclusion operators:

- **Negative Operators (Anti-Directory Filter):**
  `-site:clutch.co -site:yelp.com -site:yellowpages.com -site:zoominfo.com -site:linkedin.com -site:apollo.io -inurl:blog -inurl:news`
- **Distributor & B2B Wholesaler Intent:**
  `("become a distributor" OR "wholesale inquiry" OR "dealer portal" OR "distributor network" OR "authorized dealer")`
- **Direct Contact Anchors:**
  `("contact us" OR "sales@" OR "inquiries@")`

## 2. Token Budgeting & Pre-Enrichment Gating
To minimize token expenditure across agent iterations:
1. **Never Ingest Full Crawls:** Keep raw webpage HTML and full CSV contents out of the agent context window.
2. **ICP Verification First:** Before running `enrich_and_verify_contact`, verify that the domain represents an active business selling relevant physical/digital products.
3. **Batch Control:** Process maximum 5 candidates per iteration to keep context fresh and token-efficient.
4. **Summary Presentation:** Return discovered leads in a compact Markdown table:

| Company Name | Domain | Email Found | Phone | Status |
|---|---|---|---|---|
