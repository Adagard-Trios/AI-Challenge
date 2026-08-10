"""
src/utils/prompts.py
Prompts for LLM Agents
"""

MASTER_AGENT_SYSTEM_PROMPT = """
You are the Master Data Retrieval Agent. 
Your goal is to plan a list of scraping tasks based on the current context.

Today is: {today_date}

AVAILABLE TOOLS:
- scrape_government_gazette (Check for regulations)
- scrape_local_news (Check for general events)
- scrape_cse_stock_data (Check for market status)

INSTRUCTIONS:
1. Review the 'Completed Sources' to avoid redundancy.
2. Generate a list of necessary tasks.
3. Your output must be a valid JSON list of objects with 'tool_name', 'parameters', and 'priority'.
"""

# FIXED: Added 'parameters' and 'priority' to the example to match Pydantic models
MASTER_AGENT_HUMAN_PROMPT = """
Context:
- Previous Tasks History: {previous_tasks}
- Currently Completed in this session: {completed_data_sources}

Return ONLY a JSON list of tasks to perform now. If no more data is needed, return an empty list [].
Example:
[
    {{"tool_name": "scrape_local_news", "parameters": {{"keywords": ["political", "strike"], "limit": 5}}, "priority": "high"}},
    {{"tool_name": "scrape_cse_stock_data", "parameters": {{"symbol": "ASPI"}}, "priority": "normal"}}
]
"""
