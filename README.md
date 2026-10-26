# LeadDirect-MCP

A local, agentic Model Context Protocol (MCP) server that generates verified, direct B2B contacts with zero paid API subscriptions while slashing LLM context token consumption by over 80%.

LeadDirect connects your AI assistant (Antigravity, Claude Desktop, Cursor, or local Ollama agents) directly to the web. It autonomously discovers company contacts, uncovers hidden B2B gateways via SSL Certificate Transparency logs, extracts corporate identities through Schema.org microdata, decodes obfuscated emails, and verifies deliverability via zero-bounce SMTP checks.

---

## ⚡ Token Effectiveness & Benchmark

AI coding agents and LLMs operating unconstrained web-scraping loops suffer from **context window exhaustion** (ingesting thousands of tokens of noisy HTML, broken links, directory listings, and catch-all permutations).

LeadDirect pairs MCP backend tools with structured **Agent Skills** to solve this:

### 10-Lead B2B Campaign Benchmark

| Phase | Standard / Unconstrained Loop | LeadDirect + Skills & OSINT | Token Savings |
|---|---|---|---|
| **1. Search & Discovery** | **~1,250 tokens**<br>*(Ingests raw HTML, SEO blogs, and directory links like Yelp/Clutch)* | **~350 tokens**<br>*(Agent uses Dorking Skill; returns only verified corporate homepages)* | **-72%** |
| **2. Error Handling & Retries** | **~900 tokens**<br>*(Retries on broken file paths or blocked endpoints)* | **0 tokens**<br>*(Portable output directory & resilient fallbacks)* | **-100%** |
| **3. Contact Enrichment** | **~2,200 tokens**<br>*(Dumps un-sanitized HTML and false-positive catch-all guesses)* | **~450 tokens**<br>*(Clean JSON: extracts verified direct emails & Schema.org data)* | **-80%** |
| **4. Agent Reasoning & Synthesis** | **~1,400 tokens**<br>*(Disambiguates 50+ redundant candidate permutations)* | **~300 tokens**<br>*(Agent receives pre-structured, high-confidence rows)* | **-78%** |
| **Total Context Spent** | **~5,750 tokens** | **~1,100 tokens** | **~81% Total Reduction** |

---

## 📁 Project Structure

```text
leaddirect-mcp/
├── skills/
│   ├── b2b-lead-scout/
│   │   └── SKILL.md             # Query dorking, anti-directory filters & token budgeting
│   └── osint-lead-enrichment/
│       └── SKILL.md             # Subdomain mapping, provider heuristics & validation protocol
├── output/                      # Auto-created portable directory for CSV leads exports
├── server.py                    # FastMCP Server exposing core search, verification & OSINT tools
├── lead_hunter.py               # Deep scraping & headless Playwright engine for raw extraction
├── agent.py                     # Autonomous agent runner for local LLMs (Ollama / Qwen)
├── run_search.py                # Standalone CLI runner with targeted query batches
├── requirements.txt             # Core Python dependencies
└── README.md                    # Project documentation & benchmarks
```

---

## 🛠️ MCP Tools Reference

LeadDirect exposes three native MCP tools:

### 1. `find_distributors`
* **Input:** `query` (str), `target_leads` (int)
* **What it does:** Searches DuckDuckGo for B2B companies, filters out aggregator directories, extracts emails and phone numbers, saves results directly to `output/leads_output.csv`, and outputs a compact Markdown table.

### 2. `enrich_and_verify_contact`
* **Input:** `domain` (str), `first_name` (optional), `last_name` (optional), `website_url` (optional)
* **What it does:** Scrapes `/contact`, `/about`, and `/team` pages, decodes Cloudflare XOR-protected emails (`data-cfemail`), generates email permutations for the executive, and performs direct zero-bounce SMTP verification. Protects against false-positive catch-all loops.

### 3. `osint_recon_domain` *(New)*
* **Input:** `domain` (str)
* **What it does:** Performs zero-cost, API-key-free OSINT intelligence:
  * **SSL Certificate Transparency (crt.sh):** Enumerates hidden subdomains (`wholesale.domain.com`, `b2b.domain.com`, `dealers.domain.com`, `portal.domain.com`).
  * **Mail Infrastructure Fingerprinting:** Determines whether the target uses Google Workspace, Microsoft 365, Zoho, or self-hosted SMTP via DNS MX records.
  * **Schema.org JSON-LD Extraction:** Scrapes corporate metadata including official legal company name, direct telephone, and verified social profiles.

---

## 📦 Prerequisites & Quick Setup

### 1. Prerequisites
* **Python (3.10+)**
* **Git**
* An MCP-compatible client (**Antigravity CLI / IDE**, **Claude Desktop**, **Cursor**) or a local **Ollama** setup.

### 2. Installation
Clone the repository, install Python dependencies, and install the headless browser binary for Playwright:
```bash
git clone https://github.com/netizen4-bit/leaddirect-mcp.git
cd leaddirect-mcp
pip install -r requirements.txt
playwright install chromium
```

---

## 💻 Standalone CLI Runners (No IDE Required)

LeadDirect includes native CLI runners so you can execute lead discovery completely standalone without a desktop AI interface:

### 1. Autonomous Agent with Local LLM (`agent.py`)
Runs an autonomous lead generation agent connected to your local Ollama instance (e.g. `qwen2.5:7b`):
```bash
# Ensure Ollama is running, then launch:
python agent.py
```
Type your objective directly into the terminal prompt (e.g. *"Find 5 precision agriculture equipment distributors in Ontario"*).

### 2. Standalone Batch Query Runner (`run_search.py`)
Executes targeted, multi-query distributor discovery batches directly and exports clean data to CSV:
```bash
python run_search.py
```
*(Results are automatically saved to `output/leads_output.csv`)*.

---

## 🔌 Connecting to Your AI Client (MCP Configuration)

Add LeadDirect to your MCP configuration file (e.g. `claude_desktop_config.json` or your Antigravity / Cursor MCP configuration).

> ⚠️ **Note on Windows Paths:** In JSON strings, backslashes must be escaped (`\\`) or written with forward slashes (`/`) to prevent invalid escape errors (`\U`, `\P`, `\l`).

```json
{
  "mcpServers": {
    "leaddirect": {
      "command": "python",
      "args": [
        "C:/YOUR/PATH/TO/leaddirect-mcp/server.py"
      ],
      "env": {
        "LEADDIRECT_CSV_OUTPUT": "C:/YOUR/PATH/TO/leaddirect-mcp/output/leads_output.csv"
      }
    }
  }
}
```

* *(Alternative Windows escaped backslashes: `"C:\\YOUR\\PATH\\TO\\leaddirect-mcp\\server.py"`)*
* *(macOS / Linux: `"/Users/YOUR_NAME/Documents/leaddirect-mcp/server.py"`)*

---

## 🧠 Using the Built-in Agent Skills

LeadDirect includes native Agent Skills under `skills/`:

* **`b2b-lead-scout`**: Teaches your agent how to formulate high-precision search dorks (e.g. `-site:clutch.co -site:yelp.com ("become a distributor" OR "wholesale inquiry")`) to avoid directory junk.
* **`osint-lead-enrichment`**: Guides the agent to run subdomain discovery and mail provider checks before guessing employee email patterns.

To install the skills directly into Claude Code or compatible agents:
```bash
npx skills add netizen4-bit/leaddirect-mcp --skill b2b-lead-scout
npx skills add netizen4-bit/leaddirect-mcp --skill osint-lead-enrichment
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
