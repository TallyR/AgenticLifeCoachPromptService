import asyncio

from fastapi import FastAPI, Request

from message_api import mark_read_and_typing, save_message, send_message
from prompt_proc import process_incoming_text

app = FastAPI()

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

    # 2. Ask Sarah for a reply, using this user's notes and history.
    reply = await process_incoming_text(from_number, incoming_text)

    # 3. Send the reply back to the number it came from.
    #    (send_message also saves the outbound message to the DB.)
    await send_message(from_number, reply)
    return {"ok": True}
