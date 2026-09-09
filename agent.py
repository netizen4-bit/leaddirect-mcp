"""
LeadDirect Agent — Autonomous B2B lead generation powered by a local Ollama LLM.

Connects to a locally-running Qwen 8B model via Ollama and uses the scraping
functions from lead_hunter.py to search, scrape, and extract B2B contacts
entirely offline — no paid APIs required.

Usage:
    python agent.py
    Then type your lead-generation prompt into the terminal.
"""

import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import csv
import os
from urllib.parse import urlparse

from ollama import AsyncClient
from ddgs import DDGS
from playwright.async_api import async_playwright

# Import scraping functions from our local lead_hunter module
from lead_hunter import scrape_company_data, normalize_with_llm

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLLAMA_HOST = "http://localhost:11434"
MODEL_NAME = "my-custom-qwen"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

ollama_client = AsyncClient(host=OLLAMA_HOST)

# ---------------------------------------------------------------------------
# Tool implementations (called by the agent loop)
# ---------------------------------------------------------------------------

def search_web(query: str, max_results: int = 10) -> str:
    """Search DuckDuckGo and return results as a JSON string."""
    try:
        results = list(DDGS().text(query, max_results=max_results))
        return json.dumps(results, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def scrape_and_extract(url: str) -> str:
    """Deep-scrape a company website using Playwright and return structured contact data."""
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        data = await scrape_company_data(base_url, browser)
        await browser.close()

    # Flatten socials into the top-level dict for LLM readability
    socials = data.pop("socials", {})
    data["linkedin"] = socials.get("linkedin", [])
    data["whatsapp"] = socials.get("whatsapp", [])
    data["facebook"] = socials.get("facebook", [])
    data["instagram"] = socials.get("instagram", [])

    return json.dumps(data, indent=2, ensure_ascii=False)


def save_leads_to_csv(filename: str, leads_json: str) -> str:
    """Save a JSON array of lead dicts to a CSV file inside the output directory."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)

    try:
        leads = json.loads(leads_json)
    except json.JSONDecodeError as e:
        return f"Error parsing leads JSON: {e}"

    if not leads:
        return "No leads to save."

    fieldnames = list(leads[0].keys())
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)

    return f"Saved {len(leads)} leads to {filepath}"


# ---------------------------------------------------------------------------
# Ollama tool definitions (function-calling schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the web using DuckDuckGo. Returns a JSON array of results "
                "with 'title', 'href', and 'body' keys."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to execute.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 10).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_and_extract",
            "description": (
                "Deep-scrape a company website (homepage + /contact, /about, /team pages) "
                "using a real browser. Returns JSON with extracted emails, phones, "
                "LinkedIn, WhatsApp, Facebook, Instagram links, and raw page text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL of the company website to scrape.",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_leads_to_csv",
            "description": (
                "Save a list of lead dictionaries to a CSV file. "
                "Each dictionary should contain keys like company_name, email, phone, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The CSV filename to save as (e.g. 'uk_leads.csv').",
                    },
                    "leads_json": {
                        "type": "string",
                        "description": "A JSON string representing a list of lead dictionaries.",
                    },
                },
                "required": ["filename", "leads_json"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

async def execute_tool(name: str, args: dict) -> str:
    """Route a tool call to the correct local function."""
    print(f"\n  [🔧 Tool Call] {name}")
    print(f"      Args: {json.dumps(args, ensure_ascii=False)[:200]}")

    try:
        if name == "search_web":
            result = search_web(**args)
        elif name == "scrape_and_extract":
            result = await scrape_and_extract(**args)
        elif name == "save_leads_to_csv":
            result = save_leads_to_csv(**args)
        else:
            result = f"Error: Unknown tool '{name}'"
    except Exception as e:
        result = f"Error executing {name}: {e}"
        print(f"      [❌] {result}")
        return result

    print(f"      [✅] {len(result)} chars returned")
    return result


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are LeadDirect — an autonomous B2B lead generation agent running "
    "entirely on a local machine with no paid APIs.\n\n"
    "CAPABILITIES:\n"
    "- `search_web`: Search DuckDuckGo for companies matching the user's criteria.\n"
    "- `scrape_and_extract`: Deep-scrape a company website to extract emails, "
    "phone numbers, LinkedIn, WhatsApp, Facebook, and Instagram links.\n"
    "- `save_leads_to_csv`: Save structured leads to a local CSV file.\n\n"
    "WORKFLOW:\n"
    "1. Use `search_web` to find relevant companies.\n"
    "2. For each promising result, call `scrape_and_extract` with the URL.\n"
    "3. Analyze the scraped data to identify decision-makers and contact info.\n"
    "4. Compile all leads and call `save_leads_to_csv` to persist them.\n"
    "5. Present a final summary table to the user.\n\n"
    "RULES:\n"
    "- NEVER invent or guess URLs. Only use URLs returned by `search_web`.\n"
    "- Prefer direct personal emails over generic ones (info@, contact@).\n"
    "- Always include the company name, domain, and any discovered contacts.\n"
    "- If you cannot find a direct email, still record the company with its "
    "phone, social links, and mark email as 'Contact via website'.\n"
    "- Always pass valid JSON to tool arguments.\n"
)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

async def run_agent(user_prompt: str):
    """Main agentic loop: send prompt → handle tool calls → repeat until done."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    print(f"\n{'='*60}")
    print(f"🤖 [LeadDirect] Processing your request...")
    print(f"{'='*60}\n")

    iteration = 0
    max_iterations = 15  # Safety limit to avoid infinite loops

    while iteration < max_iterations:
        iteration += 1
        print(f"⏳ [{iteration}/{max_iterations}] Thinking...")

        try:
            response = await ollama_client.chat(
                model=MODEL_NAME,
                messages=messages,
                tools=TOOLS,
                options={"temperature": 0.1},
            )
        except Exception as e:
            print(f"\n❌ Ollama connection error: {e}")
            print("   Make sure Ollama is running: ollama serve")
            print(f"   And the model is loaded: ollama run {MODEL_NAME}")
            break

        message = response["message"]
        messages.append(message)

        # If the model produced text without tool calls, it's done
        if not message.get("tool_calls"):
            print(f"\n{'='*60}")
            print("✅ LeadDirect — Final Report")
            print(f"{'='*60}")
            print(message.get("content", "(no response)"))
            break

        # Process each tool call
        for tool_call in message["tool_calls"]:
            fn_name = tool_call["function"]["name"]
            fn_args = tool_call["function"]["arguments"]

            tool_result = await execute_tool(fn_name, fn_args)

            messages.append({
                "role": "tool",
                "content": str(tool_result),
                "name": fn_name,
            })
    else:
        print(f"\n⚠️  Reached iteration limit ({max_iterations}). Stopping.")


# ---------------------------------------------------------------------------
# Interactive terminal entry point
# ---------------------------------------------------------------------------

def main():
    """Interactive terminal loop — type a prompt, get leads."""
    print(r"""
  _                    _ ____  _               _
 | |    ___  __ _  __| |  _ \(_)_ __ ___  ___| |_
 | |   / _ \/ _` |/ _` | | | | | '__/ _ \/ __| __|
 | |__|  __/ (_| | (_| | |_| | | | |  __/ (__| |_
 |_____\___|\__,_|\__,_|____/|_|_|  \___|\___|\__|

  Autonomous B2B Lead Generation Agent
  Powered by local Ollama + Qwen · No paid APIs
""")
    print(f"  Model:  {MODEL_NAME}")
    print(f"  Ollama: {OLLAMA_HOST}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Type 'quit' or 'exit' to stop.\n")

    while True:
        try:
            prompt = input("🔎 Enter your lead-gen prompt:\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            print("👋 Goodbye!")
            break

        asyncio.run(run_agent(prompt))
        print()


if __name__ == "__main__":
    main()
