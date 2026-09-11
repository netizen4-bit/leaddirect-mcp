# LeadDirect-MCP

A local, for Agentic Workflow Model Context Protocol (MCP) tool that generates verified, direct B2B contacts while minimizing LLM token spend. Built specifically for Small Companies and Startups to run completely locally and privately.

LeadDirect connects your AI assistant directly to the web. It autonomously discovers company contacts, scrapes homepages, and decodes hidden data to extract **direct employee email addresses** (going beyond generic `info@` or `sales@` inboxes). Additionally, it captures key social media and communication links—including **LinkedIn, WhatsApp, Facebook, and Instagram**—and verifies that the emails are active, all without expensive API subscriptions.

---

## 🛠️ Prerequisites

Before installing, you need a few basic tools installed on your computer:
1. **[Python (3.10+)](https://www.python.org/downloads/)** — The programming language this runs on.
2. **[Git for Windows/Mac](https://git-scm.com/downloads)** — Used to download this repository.
3. **An MCP-Compatible AI Client** — You need an AI to command the scraper. Choose one:
   * **[Claude Desktop](https://claude.ai/download)** (Recommended for ease of use)
   * **[Cursor IDE](https://cursor.sh/)** (For developers)
   * **[Antigravity CLI](https://antigravity.google/product/antigravity-cli)** (For local terminal users)

---

## 🚀 Quick Start Guide

Open your terminal (**Command Prompt** or **PowerShell** on Windows, or **Terminal** on Mac/Linux) and run these commands:

```bash
git clone https://github.com/netizen4-bit/leaddirect-mcp
cd leaddirect-mcp
pip install -r requirements.txt
```

---

## 🔗 Connecting to your AI (MCP Client Configuration)

To let your AI use this scraper, you must tell it where this folder is located on your computer.

Add LeadDirect to your MCP client configuration file (e.g., `claude_desktop_config.json`):

> ⚠️ **IMPORTANT:** You MUST replace the `args` path below with the exact location where you downloaded this folder on your computer.

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

* *(Example for Windows: `"C:\\Users\\YOUR_NAME\\Documents\\leaddirect-mcp\\server.py"`)*
* *(Example for Mac/Linux: `"/Users/YOUR_NAME/Documents/leaddirect-mcp/server.py"`)*

---

## 📁 Project Structure

```text
leaddirect-mcp/
├── server.py          # The core Bridge. Connects the tools to your AI client.
├── agent.py           # The Agent. Designed for Local LLM. Connects directly to local Ollama setups.
├── lead_hunter.py     # The scraping engine (the tool) that executes web searches.
├── run_search.py      # A manual terminal runner for testing outside of an AI environment.
├── requirements.txt   # Python dependencies
└── README.md          # Project documentation
```

---

## 🧰 Tools Reference & Prompting

### 🧠 How to Structure High-Converting Prompts

Because LeadDirect operates autonomously, the quality of your leads depends on strict filtering instructions:

1. **Target & Geography:** The niche and specific country/region.
2. **Local Language Keywords:** Use local native terms for foreign markets (e.g., `semi-remorque surbaissée` for France).
3. **Negative Constraints (Crucial):** Explicitly list large global brands and aggregator portals to skip.
4. **Qualification Rules:** Specify that the site must sell physical products directly.

---

### ⚠️ Pro-Tip: How to Get DIRECT Emails (Not just info@)

Because of spam, modern companies rarely put employee emails directly on their public websites. 

Tool #1 (`find_distributors`) gathers public domain data. To get direct contacts, instruct your AI client to chain **both** tools in a two-step process:

**The Chained Prompt Formula:**
> "I need 5 B2B contacts for **[Niche Product]** dealers in **[Target Country]**. 
> 
> **Step 1:** Use your search tool to find the companies. Skip big brands like **[Giant Brand 1]**.
> 
> **Step 2:** Once you have the domains, use your `enrich_and_verify_contact` tool on each domain to generate and test direct employee email permutations (e.g., first.last@domain.com, director@domain.com) so I get direct contacts, not just the generic info@ emails. 
> 
> Put the final results in a table, including their social media links."

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
