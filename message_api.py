# This is where you can send messages:
# {phoneNumber: 999-999-9999 | AGENT, text: "Test"}
# should be an async function

import os
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from supabase import AsyncClient, create_async_client

load_dotenv()

TABLE = "MessageTable"

_client: AsyncClient | None = None

async def _get_client() -> AsyncClient:
    """Create the Supabase client once and reuse it on later calls."""
    global _client
    if _client is None:
        _client = await create_async_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
    return _client

async def save_message(
    message: str, from_phone_number: str, to_phone_number: str
) -> dict:
    """Save a message. Use "AGENT" for whichever side is the agent.
    id and sent_at are filled in by the DB."""
    client = await _get_client()
    print("trying to save: ")
    response = await (
        client.table(TABLE)
        .insert(
            {
                "message": message,
                "from_phone_number": from_phone_number,
                "to_phone_number": to_phone_number,
            }
        )
        .execute()
    )
    return response.data[0]


async def send_message(phone_number: str, message: str) -> dict:
    """Send an outbound message via Blooio, mark the chat read, then save it."""
    chat_id = quote(phone_number, safe="")
    auth = {"Authorization": f"Bearer {os.environ['BLOOIO_API_KEY']}"}
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"https://api.blooio.com/v2/api/chats/{chat_id}/messages",
            headers={**auth, "Content-Type": "application/json"},
            json={"text": message},
        )
        # fire-and-forget read receipt; don't let it break a successful send
        await client.post(
            f"https://api.blooio.com/v2/api/chats/{chat_id}/read",
            headers=auth,
        )
    res.raise_for_status()
    await save_message(message, from_phone_number="AGENT", to_phone_number=phone_number)
    return res.json()
