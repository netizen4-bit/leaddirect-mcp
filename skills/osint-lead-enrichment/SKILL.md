---
name: osint-lead-enrichment
description: Systematic OSINT enrichment protocol using SSL certificate transparency subdomains, mail provider fingerprinting, and zero-bounce SMTP verification.
version: 1.0.0
---

# OSINT Lead Enrichment Protocol

## Role & Purpose
Orchestrates multi-layer corporate intelligence using `osint_recon_domain` and `enrich_and_verify_contact`. Uncovers hidden B2B gateways and identifies corporate email infrastructure without paid API subscriptions.

## 1. Reconnaissance Waterfall
1. **Execute `osint_recon_domain`**:
   - Check SSL Certificate Transparency logs (crt.sh) for subdomains like `wholesale.domain.com`, `b2b.domain.com`, `dealers.domain.com`, `portal.domain.com`.
   - Inspect DNS MX records to determine the email provider:
     - **Google Workspace** (`aspmx.l.google.com`): High confidence patterns are `{first}@{domain}` and `{first}.{last}@{domain}`.
     - **Microsoft 365** (`mail.protection.outlook.com`): High confidence patterns are `{first}.{last}@{domain}` and `{f}{last}@{domain}`.
     - **Zoho / Self-Hosted**: Probe for catch-all behavior.
   - Extract Schema.org JSON-LD microdata for official legal entity names, direct telephone numbers, and verified social media links.

2. **Execute `enrich_and_verify_contact`**:
   - De-obfuscate Cloudflare-protected email links (`data-cfemail`).
   - Run zero-bounce SMTP validation.
   - If the domain has a catch-all configuration (`catch_all_domain: true`), prioritize scraped website emails over permuted guesses to avoid email bounce traps.
