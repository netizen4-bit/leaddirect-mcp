# LeadDirect-MCP

A high-performance B2B lead generation and email verification MCP server powered by [FastMCP](https://github.com/jlowin/fastmcp).

LeadDirect discovers company contacts via DuckDuckGo, scrapes websites for emails and phone numbers, decodes Cloudflare-obfuscated emails, generates corporate email permutations, validates MX records, and performs zero-bounce SMTP handshakes — all exposed as MCP tools for any LLM client.

---

## Features

| Tool | Description |
|---|---|
| `find_distributors` | Bulk B2B discovery — searches DuckDuckGo, scrapes homepages, extracts emails/phones, deduplicates against a CSV, and returns a Markdown table. |
| `enrich_and_verify_contact` | Deep enrichment pipeline — Cloudflare XOR de-obfuscation, pattern permutation engine, DNS MX resolution, and zero-bounce async SMTP verification. |

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-org/leaddirect-mcp.git
cd leaddirect-mcp
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the server

```bash
python server.py
# or
mcp dev server.py
```

---

## MCP Client Configuration

Add LeadDirect to your MCP client (e.g., Claude Desktop, Gemini, Cursor) by adding the following to your client configuration:

```json
{
  "mcpServers": {
    "leaddirect": {
      "command": "python",
      "args": ["C:\\Users\\lenovo\\.gemini\\antigravity\\scratch\\lead_gen_mcp\\server.py"]
    }
  }
}
```

---

## Project Structure

```
leaddirect-mcp/
├── server.py          # FastMCP server — all MCP tools and pipeline modules
├── agent.py           # Ollama-based autonomous agent that consumes the tools
├── lead_hunter.py     # Standalone lead hunting utilities
├── run_search.py      # CLI search runner
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

---

## Tools Reference

### `find_distributors(query, target_leads=10)`

Searches DuckDuckGo for B2B companies matching `query`, scrapes their homepages for contact info, deduplicates against `leads_output.csv`, and appends new leads.

**Returns:** Markdown table with columns `Company | Domain | Email | Phone`.

### `enrich_and_verify_contact(domain, first_name?, last_name?, website_url?)`

Deep enrichment pipeline for a single domain/contact:

1. **Cloudflare de-obfuscation** — decodes `data-cfemail` and `/cdn-cgi/l/email-protection#` patterns.
2. **Email permutations** — generates `first.last@`, `flast@`, `first@`, etc. from a contact name.
3. **MX resolution** — queries DNS MX records via `dnspython`.
4. **SMTP verification** — zero-bounce handshake on port 25 with catch-all detection.

**Returns:** Dictionary with `mx_hosts`, `scraped_emails`, `cf_decoded_emails`, `permuted_candidates`, `verified` (with SMTP status per email), and `catch_all_domain` flag.

---

## License

MIT
