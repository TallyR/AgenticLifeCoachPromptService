# Full end-to-end terminal harness: runs the SAME function calls as api.py's
# /blooio handler, in the same order, with your typed message standing in for
# the Blooio payload. No server involved. Every side effect is real: dedup,
# read/typing receipts, DB saves, the agent loop and its tools, send retries,
# and the actual Blooio send — Faro's reply lands on TEST_NUMBER's phone.

import asyncio

from api import FIRST_CONTACT_GREETING, _send_with_retries
from dedupe_messages import is_duplicate
from message_api import mark_read_and_typing, save_message, send_contact_greeting
from prompt_proc import mark_contact_message_sent, process_incoming_text

TEST_NUMBER = "+18323346991"


async def main() -> None:
    print(f"texting Faro as {TEST_NUMBER}, same calls as the prod webhook")
    print("replies are actually sent to that phone. empty message or Ctrl+C to quit")

    while True:
        try:
            incoming = input("\nYOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not incoming:
            break

        # --- api.py's blooio_webhook, call for call ---

        # 0. drop duplicate deliveries
        if await is_duplicate(TEST_NUMBER, incoming):
            print(f"REPEAT DETECTED DROPPING: {TEST_NUMBER}: {incoming}")
            continue

        # 1. read receipt + typing indicator, in parallel with saving the
        #    incoming message (from user, to agent)
        await asyncio.gather(
            mark_read_and_typing(TEST_NUMBER),
            save_message(
                incoming,
                from_phone_number=TEST_NUMBER,
                to_phone_number="AGENT",
            ),
        )

        # 2. the production brain (prints tool calls + reply itself)
        reply, send_contact_card = await process_incoming_text(
            TEST_NUMBER, incoming
        )

        # 3. send the reply for real, with prod's retry wrapper
        #    (send_message inside also saves the outbound message)
        await _send_with_retries(TEST_NUMBER, reply)

        # 4. first-contact follow-up, exactly like prod
        if send_contact_card:
            await mark_read_and_typing(TEST_NUMBER)
            await send_contact_greeting(TEST_NUMBER, FIRST_CONTACT_GREETING)
            await mark_contact_message_sent(TEST_NUMBER)


if __name__ == "__main__":
    asyncio.run(main())
