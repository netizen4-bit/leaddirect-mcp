import asyncio
import json
from ollama import AsyncClient

# Import the tool functions directly from our server
from server import search_web, extract_webpage_content, save_structured_leads

# Initialize Ollama async client
ollama_client = AsyncClient(host='http://localhost:11434')
MODEL_NAME = 'my-custom-qwen'

# Define the tools for Ollama based on the native definitions
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web using DuckDuckGo. Returns a JSON string containing search results (title, link, snippet).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to execute."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return. Default is 10."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_webpage_content",
            "description": "Scrape and extract text content from a webpage using Playwright. Returns LLM-ready text content from the target URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL of the webpage to scrape and extract text from."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_structured_leads",
            "description": "Save extracted leads data into a structured format (JSON or CSV).",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The filename to save as (e.g. leads.csv)."
                    },
                    "leads": {
                        "type": "string",
                        "description": "A JSON string representing a list of dictionaries. Each dictionary must contain lead information."
                    },
                    "output_format": {
                        "type": "string",
                        "description": "The format to save in: 'json' or 'csv'."
                    }
                },
                "required": ["filename", "leads"]
            }
        }
    }
]

async def execute_tool(name: str, args: dict) -> str:
    """Safely execute the requested tool with error handling."""
    print(f"\n[🔧 Executing Tool] {name}")
    print(f"    Arguments: {json.dumps(args)}")
    try:
        # We can call the FastMCP wrapped functions just like normal async functions
        if name == 'search_web':
            return await search_web(**args)
        elif name == 'extract_webpage_content':
            return await extract_webpage_content(**args)
        elif name == 'save_structured_leads':
            return await save_structured_leads(**args)
        else:
            return f"Error: Unknown tool {name}"
    except Exception as e:
        error_msg = f"Error executing {name}: {str(e)}"
        print(f"    [❌ Error] {error_msg}")
        return error_msg

async def run_agent(prompt: str):
    """Main execution loop for the agent."""
    messages = [
        {
            'role': 'system', 
            'content': (
                "You are LeadDirect — an expert B2B lead generation researcher (similar to Apollo.io or Hunter.io). "
                "Your goal is to find DIRECT CONTACTS (decision-makers like CEOs, Founders, or Directors) "
                "for target companies. \n\n"
                "STRICT RULES:\n"
                "- CRITICAL: NEVER invent, guess, or hallucinate URLs. When calling `extract_webpage_content`, you MUST exclusively use the exact URL strings returned by the `search_web` tool. Read the search results carefully to extract the real links.\n"
                "- DO NOT scrape or save generic emails (e.g., info@, contact@, hello@, sales@, support@).\n"
                "- You must find a specific person's name and their title.\n"
                "- Search for their direct email or deduce it (e.g., first.last@company.com, first@company.com) by searching the web or scraping their /about or /team pages.\n"
                "- Compile the leads into a structured list including person_name, title, direct_email, and company_name.\n"
                "Always pass valid JSON objects to tools."
            )
        },
        {'role': 'user', 'content': prompt}
    ]
    
    print(f"🤖 [LeadDirect] Task: {prompt}\n")
    
    while True:
        try:
            print("⏳ Waiting for model response...")
            response = await ollama_client.chat(
                model=MODEL_NAME,
                messages=messages,
                tools=tools
            )
            
            message = response['message']
            messages.append(message)
            
            # If the model didn't call any tools, it's done
            if not message.get('tool_calls'):
                print("\n✅ Agent final response:")
                print(message.get('content', ''))
                break
                
            # Handle tool calls iteratively
            for tool_call in message['tool_calls']:
                function_name = tool_call['function']['name']
                arguments = tool_call['function']['arguments']
                
                # Execute tool
                tool_result = await execute_tool(function_name, arguments)
                print(f"    [✅ Result Length] {len(str(tool_result))} characters")
                
                # Append tool result to messages so the model can read it
                messages.append({
                    'role': 'tool',
                    'content': str(tool_result),
                    'name': function_name
                })
                
        except Exception as e:
            print(f"\n❌ Error during agent execution: {str(e)}")
            break

if __name__ == "__main__":
    # Test query for B2B direct lead generation
    test_prompt = "Search for 2 digital marketing agencies in Chicago. Find the specific name, title, and direct email address of a decision-maker (CEO, Founder, or Director) at each agency. STRICTLY avoid generic info@ emails. Compile this into a structured JSON list and save it as 'chicago_decision_makers.csv'."
    asyncio.run(run_agent(test_prompt))
