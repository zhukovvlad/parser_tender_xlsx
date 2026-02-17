"""Client manager with context manager support."""

from contextlib import asynccontextmanager
from google import genai


class ClientManager:
    """Manages Google GenAI client lifecycle."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    @asynccontextmanager
    async def get_client(self):
        """Create and properly close async client."""
        client = genai.Client(api_key=self.api_key)
        aclient = client.aio
        try:
            yield aclient
        finally:
            await aclient.aclose()
