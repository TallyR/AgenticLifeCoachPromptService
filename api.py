import json

from fastapi import FastAPI, Request
from message_api import save_message, send_message

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": {"name": "John", "age": 30}}

 #async is un-needed because it runs this function in a diff thread 
 #so for data processing heavy functions that are sync; DONT use async lmao
 #use Sendblue -> this current api is hot garbage
@app.post("/blooio")
async def blooio_webhook(request: Request):
    print(request)
    payload = await request.json()
    print(payload)

    # Only act on inbound messages; ack everything else (sent, delivered, etc.)
    if payload.get("event") != "message.received":
        return {"ok": True}

    # save_message(message, from_phone_number, to_phone_number)
    await save_message(
        payload.get('text'),
        from_phone_number=payload.get('sender'),
        to_phone_number="AGENT",
    )
    await send_message(
        phone_number=payload.get('sender'),
        message=f"Fuck yo, '{payload.get('text')}'"
    )
    print(f"Here is the text you were text:\n   {payload.get('text')}")
    return {"ok": True}
