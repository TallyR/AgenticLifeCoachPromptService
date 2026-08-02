import asyncio

import httpx
from fastapi import FastAPI, Request

from dedupe_messages import is_duplicate
from message_api import (
    mark_read_and_typing,
    save_message,
    send_contact_greeting,
    send_message,
)
from prompt_proc import mark_contact_message_sent, process_incoming_text

app = FastAPI()

FIRST_CONTACT_GREETING = (
    "oh, also, here is my contact card you should save in order to make sure "
    "you can find me again :)"
)

# Max model rounds per agent turn (call -> tools -> call -> ...). The runaway
# guard for the agent loop; shared by the debug harnesses and, once tools are
# wired into production, process_incoming_text.
AGENT_TURN_LIMIT = 10

# Blooio sends flake sometimes: retry up to 3 attempts, 6s apart.
SEND_RETRY_ATTEMPTS = 3
SEND_RETRY_DELAY_SECONDS = 6


async def _send_with_retries(phone_number: str, message: str) -> None:
    """send_message, retried on DELIVERY failures only (httpx errors: network
    trouble or a Blooio 4xx/5xx). A failure in the DB save that runs after a
    successful send is NOT retried — retrying that would text the user the
    same message twice. Gives up loudly after the last attempt so the webhook
    still returns ok (a raise would just make Blooio redeliver, which dedup
    drops anyway)."""
    for attempt in range(1, SEND_RETRY_ATTEMPTS + 1):
        try:
            await send_message(phone_number, message)
            return
        except httpx.HTTPError as e:
            print(f"send attempt {attempt}/{SEND_RETRY_ATTEMPTS} failed: {e}")
            if attempt < SEND_RETRY_ATTEMPTS:
                # asyncio.sleep, never time.sleep: parks only this request,
                # the event loop keeps serving everyone else for the 6s.
                await asyncio.sleep(SEND_RETRY_DELAY_SECONDS)
    print(f"GIVING UP: could not send to {phone_number} after {SEND_RETRY_ATTEMPTS} attempts")

@app.get("/")
def read_root():
    return {"message": {"name": "John", "age": 30}}

 #async is un-needed because it runs this function in a diff thread 
 #so for data processing heavy functions that are sync; DONT use async lmao
 #use Sendblue -> this current api is hot garbage
@app.post("/blooio")
async def blooio_webhook(request: Request):
    payload = await request.json()
    # Only act on inbound messages; ack everything else (sent, delivered, etc.)
    if payload.get("event") != "message.received":
        return {"ok": True}
    print("Got this message:\n")
    print(payload)

    from_number = payload.get("sender")
    incoming_text = payload.get("text")

    # 0. Drop duplicate deliveries (Blooio retries). Still return ok —
    #    anything else makes Blooio keep retrying forever.
    if await is_duplicate(from_number, incoming_text):
        print(f"REPEAT DETECTED DROPPING: {from_number}: {incoming_text}")
        return {"ok": True}

    # 1. Fire read receipt + typing indicator the moment the webhook lands,
    #    in parallel with saving the incoming message (from user, to agent).
    await asyncio.gather(
        mark_read_and_typing(from_number),
        save_message(
            incoming_text,
            from_phone_number=from_number,
            to_phone_number="AGENT",
        ),
    )

    # 2. Ask Faro for a reply, using this user's notes and history.
    reply, send_contact_card = await process_incoming_text(from_number, incoming_text)

    # 3. Send the reply back to the number it came from, with retries.
    #    (send_message also saves the outbound message to the DB.)
    await _send_with_retries(from_number, reply)

    # 4. If this user hasn't gotten Faro's contact card yet, follow up with it
    #    (fresh typing indicator so it reads like a second text being typed),
    #    then record that it was sent so it never goes out twice.
    if send_contact_card:
        await mark_read_and_typing(from_number)
        await send_contact_greeting(from_number, FIRST_CONTACT_GREETING)
        await mark_contact_message_sent(from_number)

    return {"ok": True}
