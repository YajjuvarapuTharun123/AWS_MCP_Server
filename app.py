from fastmcp import FastMCP
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession, McpError, types
from contextlib import AsyncExitStack
from typing import Optional, List, Union
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aws-knowledge")

def format_content(content) -> str:
    """Helper to extract text from content blocks, pretty-printing JSON if possible"""
    formatted_texts = []
    for c in content:
        if c.type == "text":
            try:
                # Try to parse and pretty-print if it's JSON
                parsed = json.loads(c.text)
                
                # Unwrap common AWS response structure to reduce nesting
                if isinstance(parsed, dict) and "content" in parsed and isinstance(parsed["content"], dict):
                    result = parsed["content"].get("result")
                    if isinstance(result, dict):
                        parsed = result
                        
                        # Remove null fields that confuse users
                        if parsed.get("next_token") is None:
                            parsed.pop("next_token", None)
                        if parsed.get("failed_regions") is None:
                            parsed.pop("failed_regions", None)

                formatted_texts.append(json.dumps(parsed, indent=2))
            except (json.JSONDecodeError, TypeError):
                formatted_texts.append(c.text)
    return "\n".join(formatted_texts)


# Init MCP server
mcp = FastMCP("aws-knowledge")

# AWS Knowledge MCP endpoint
AWS_MCP_URL = "https://knowledge-mcp.global.api.aws"
AWS_REGION = "us-east-1"


# AWS Knowledge client
# We use a context manager for each request to avoid async context issues
class AWSClientContext:
    def __init__(self):
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        try:
            read, write, _ = await self.stack.enter_async_context(
                streamable_http_client(
                    url=AWS_MCP_URL,
                )
            )
            session = await self.stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            return session
        except Exception as e:
            await self.stack.aclose()
            logger.error(f"Failed to connect to AWS MCP: {e}")
            raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message=f"Connection Error: {str(e)}"))

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stack.aclose()


# ---------------- TOOLS ---------------- #

@mcp.tool("search_documentation", description="Search across all AWS documentation with optional topic-based filtering")
async def search_documentation(query: str, topics: Optional[List[str]] = None):
    async with AWSClientContext() as session:
        try:
            # Upstream tool uses 'search_phrase' instead of 'query'
            args = {"search_phrase": query}
            if topics:
                args["topics"] = topics
            result = await session.call_tool("aws___search_documentation", args)
            return format_content(result.content)
        except Exception as e:
            return f"Error searching documentation: {str(e)}"


@mcp.tool("read_documentation", description="Retrieve and convert AWS documentation pages to markdown")
async def read_documentation(url: str, start_index: Optional[int] = None, max_length: Optional[int] = None):
    async with AWSClientContext() as session:
        try:
            args = {"url": url}
            if start_index is not None:
                args["start_index"] = start_index
            if max_length is not None:
                args["max_length"] = max_length
            result = await session.call_tool("aws___read_documentation", args)
            return format_content(result.content)
        except Exception as e:
             return f"Error reading documentation: {str(e)}"


@mcp.tool("recommend", description="Get content recommendations for AWS documentation pages")
async def recommend(url: str):
    async with AWSClientContext() as session:
        try:
            result = await session.call_tool("aws___recommend", {"url": url})
            return format_content(result.content)
        except Exception as e:
             return f"Error getting recommendations: {str(e)}"


@mcp.tool("list_regions", description="Retrieve a list of all AWS regions, including their identifiers and names")
async def list_regions():
    async with AWSClientContext() as session:
        try:
            result = await session.call_tool("aws___list_regions", {})
            return format_content(result.content)
        except Exception as e:
             return f"Error listing regions: {str(e)}"


@mcp.tool("get_regional_availability", description="Retrieve AWS regional availability information. resource_type must be one of: 'product' (e.g. 'AWS Lambda'), 'api' (e.g. 'EC2'), or 'cfn' (e.g. 'AWS::EC2::Instance'). filters is a list of specific resource names to check.")
async def get_regional_availability(resource_type: str, region: str = "us-east-1", filters: Union[List[str], str, None] = None):
    async with AWSClientContext() as session:
        try:
            # resource_type must be 'product', 'api', or 'cfn'
            args = {"resource_type": resource_type, "region": region}
            
            if filters:
                if isinstance(filters, str):
                    try:
                        parsed = json.loads(filters)
                        if isinstance(parsed, list):
                            filters = parsed
                        else:
                            filters = [filters]
                    except json.JSONDecodeError:
                        filters = [filters]
                args["filters"] = filters
                
            result = await session.call_tool("aws___get_regional_availability", args)
            return format_content(result.content)
        except Exception as e:
             return f"Error checking availability: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="sse")
