# LeadDirect-MCP

A local, agentic Model Context Protocol (MCP) tool that generates verified, direct B2B contacts while minimizing LLM token spend. Built specifically for Small Companies and Startups to run completely locally and privately.

LeadDirect connects your AI assistant directly to the web. It autonomously discovers company contacts, scrapes homepages, and decodes hidden data to extract **direct employee email addresses** (going beyond generic `info@` or `sales@` inboxes). Additionally, it captures key social media and communication links—including **LinkedIn, WhatsApp, Facebook, and Instagram**—and verifies that the emails are active, all without expensive API subscriptions.

---

## 🛠️ Prerequisites

Before installing, you need a few basic tools installed on your computer:
1. **[Python (3.10+)](https://www.python.org/downloads/)** — The programming language this runs on.
2. **[Git for Windows/Mac](https://git-scm.com/downloads)** — Used to download this repository.
3. **An MCP-Compatible AI Client** — You need an AI to command the scraper. Choose one:
   * **[Claude Desktop](https://claude.ai/download)** (Recommended for ease of use)
   * **[Cursor IDE](https://cursor.sh/)** (For developers)
   * **Antigravity CLI** (For local terminal users)

---
## 🚀 Quick Start Guide

Open your terminal (**Command Prompt** or **PowerShell** on Windows, or **Terminal** on Mac/Linux) and run these commands exactly as written:

```bash
git clone [https://github.com/netizen4-bit/leaddirect-mcp.git](https://github.com/netizen4-bit/leaddirect-mcp.git)
cd leaddirect-mcp
pip install -r requirements.txt

---

## Connecting to your AI (MCP Client Configuration)
To let your AI use this scraper, you must tell it where this folder is located on your computer.

Add LeadDirect to your MCP client (e.g., Claude Desktop, Gemini, Cursor) by adding the following to your client configuration.
Add the following code to your AI client's configuration file (e.g., claude_desktop_config.json).

⚠️ IMPORTANT: You MUST change the "args" path below to match the exact location where you downloaded this folder on your computer!

```json
{
  "mcpServers": {
    "leaddirect": {
      "command": "python",
      "args": ["C:\\YOUR\\EXACT\\PATH\\HERE\\leaddirect-mcp\\server.py"]
    }
  }
}
```
(Example for Windows: "C:\\Users\\YOUR_NAME\\Documents\\leaddirect-mcp\\server.py")
(Example for Mac: "/Users/YOUR_NAME/Documents/leaddirect-mcp/server.py")

---

## Project Structure

```
leaddirect-mcp/
├── server.py          # The core bridge that connects the tools to your AI client.
├── agent.py           # Script designed for Local LLM. It connects directly to local Ollama setups, running models completely offline for maximum privacy and zero token costs.
├── lead_hunter.py     # The scraping engine that does the actual web searching.
├── run_search.py      # A manual terminal runner for testing outside of an AI environment.
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

---

## Reference

### ⚠️ Pro-Tip: How to Get DIRECT Emails (Not just info@)

Because of spam, 99% of modern companies hide their employee emails and only publish generic addresses like `info@` or `sales@` on their public websites. 

Tool #1 (`find_distributors`) only scrapes what is publicly visible on the website. To get real, direct contacts, you must command the AI to chain **both** tools together in a two-step process:

**The "Chained" Prompt Formula:**
> "I need 5 B2B contacts for **[Niche Product]** dealers in **[Target Country]**. 
>
> **Step 1:** Use your search tool to find the companies. Skip big brands like **[Giant Brand 1]**.
> 
> **Step 2:** Once you have the domains, use your `enrich_and_verify_contact` tool on each domain to generate and test direct employee email permutations (e.g., first.last@domain.com, director@domain.com) so I get direct contacts, not just the generic info@ emails. 
>
> Put the final results in a table, including their social media links."

---

## License

MIT
