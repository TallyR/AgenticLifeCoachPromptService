# Terminal harness: runs the SAME function calls as api.py's /blooio handler,
# in the same order, with your typed message standing in for the Blooio
# payload. No server involved.
#
# DRY_RUN toggles two modes:
#   False (LIVE): every side effect is real — dedup, read/typing receipts, DB
#     saves, the agent loop and its tools, send retries, and the actual Blooio
#     send. Faro's reply lands on TEST_NUMBER's phone.
#   True (DRY): feed messages and exercise the brain + its tools, but record
#     NO conversation state — the incoming message isn't saved, the reply isn't
#     sent or saved, no receipts, no dedup. The ONE thing that still persists is
#     tool use: create_event / create_reminder / delete write to their tables,
#     because testing tool behavior is the whole point of the dry run.

import asyncio

from api import FIRST_CONTACT_GREETING, _send_with_retries
from dedupe_messages import is_duplicate
from message_api import FARO_VCF_URL, mark_read_and_typing, save_message
from prompt_proc import mark_contact_message_sent, process_incoming_text

TEST_NUMBER = "+18323346991"
DRY_RUN = False


async def main() -> None:
    mode = (
        "DRY RUN — no state recorded, but tools still fire"
        if DRY_RUN
        else "LIVE — real texts sent, real saves"
    )
    print(f"texting Faro as {TEST_NUMBER}  [{mode}]")
    print("empty message or Ctrl+C to quit")

    while True:
        try:
            incoming = input("\nYOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not incoming:
            break

        # --- api.py's blooio_webhook, call for call ---

        # Steps 0/1 record state (dedup file, MessageTable) and hit the phone
        # (receipts). Skipped entirely in a dry run.
        if not DRY_RUN:
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

        # 2. the production brain — runs in BOTH modes. It prints the tool
        #    calls and the reply itself. Tool calls DO write to the event /
        #    reminder tables even in a dry run: that's the point.
        reply, send_contact_card = await process_incoming_text(
            TEST_NUMBER, incoming
        )

        # Dry run stops here: reply printed above by process_incoming_text,
        # nothing sent, nothing saved.
        if DRY_RUN:
            print("[dry run] reply above was NOT sent; no conversation state recorded")
            continue

        # 3. send the reply for real, with prod's retry wrapper
        #    (send_message inside also saves the outbound message)
        await _send_with_retries(TEST_NUMBER, reply)

        # 4. first-contact follow-up, exactly like prod
        if send_contact_card:
            await mark_read_and_typing(TEST_NUMBER)
            # contact card = greeting + Faro's .vcf attached (mirrors api.py step 4)
            await _send_with_retries(
                TEST_NUMBER, FIRST_CONTACT_GREETING, attachments=[FARO_VCF_URL]
            )
            await mark_contact_message_sent(TEST_NUMBER)


if __name__ == "__main__":
    asyncio.run(main())
