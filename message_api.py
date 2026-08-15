# This is where you can send messages:
# { phoneNumber: 999-999-9999 | AGENT, text: "Test" }
# should be an async function

import os
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from supabase import AsyncClient, create_async_client

load_dotenv()

TABLE = "MessageTable"
# The final URL after redirects — justtextfaro.com 308s to www; attachment
# fetchers don't always follow redirects, so link the file directly.
FARO_VCF_URL = "https://www.justtextfaro.com/faro.vcf"

# Blooio's send endpoint can be slow to respond; give it room before timing
# out (httpx defaults to 5s). Applies per phase: connect, read, write, pool.
BLOOIO_TIMEOUT_SECONDS = 30

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


async def mark_read_and_typing(phone_number: str) -> None:
    """Fire the read receipt, then the typing indicator, for better UX while
    the agent thinks. Best-effort: a failure here must never break the reply."""
    chat_id = quote(phone_number, safe="")
    auth = {"Authorization": f"Bearer {os.environ['BLOOIO_API_KEY']}"}
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.blooio.com/v2/api/chats/{chat_id}/read",
                headers=auth,
            )
            await client.post(
                f"https://api.blooio.com/v2/api/chats/{chat_id}/typing",
                headers=auth,
            )
    except httpx.HTTPError as e:
        print(f"read/typing failed (ignoring): {e}")


async def send_message(
    phone_number: str,
    message: str,
    idempotency_key: str,
    attachments: list[str] | None = None,
) -> dict:
    """Send an outbound message via Blooio; on success, save it to the DB.

    Prefer calling this through `_send_with_retries` below rather than
    directly: that wrapper mints the idempotency key, keeps it stable across
    retries, and handles delivery failures. Call here directly only when you
    have a reason to skip retries, and generate your own key with
    `str(uuid.uuid4())`.

    idempotency_key: required, and MUST be the SAME across every retry of a
    single logical send — so a retry after a timeout can't double-text the
    user. Blooio replays the original response (200 + original message_id)
    for a repeated key instead of sending again.
    attachments: optional list of file URLs (e.g. a .vcf contact card) to
    attach. When present, the saved DB message notes them."""
    chat_id = quote(phone_number, safe="")
    body: dict = {"text": message}
    if attachments:
        body["attachments"] = attachments
    async with httpx.AsyncClient(timeout=BLOOIO_TIMEOUT_SECONDS) as client:
        res = await client.post(
            f"https://api.blooio.com/v2/api/chats/{chat_id}/messages",
            headers={
                "Authorization": f"Bearer {os.environ['BLOOIO_API_KEY']}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
            json=body,
        )
    res.raise_for_status()
    saved_message = message
    if attachments:
        saved_message = f"{message}\nATTACHMENT: ({', '.join(attachments)})"
    try:
        await save_message(
            saved_message, from_phone_number="AGENT", to_phone_number=phone_number
        )
    except Exception as e:
        # The text already went out — a failed save is a history gap, not a
        # failed send. Print everything needed to backfill the row by hand.
        print(
            f"SAVE FAILED for sent message (AGENT -> {phone_number}): {e}\n"
            f"  message was: {saved_message}"
        )
    return res.json()
