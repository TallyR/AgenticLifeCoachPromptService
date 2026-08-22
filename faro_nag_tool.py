import asyncio

from message_api import _get_client

NAG_TABLE = "DailyNagTable"


async def create_nag(nag_note: str, user_number: str) -> dict:
    """Write one nag to the DailyNagTable and return the row.

    A nag is a standing "keep after me until it's done" item with no set
    time — it rides the daily morning rundown rather than firing as an
    alarm. `id` and `created_at` are filled in by the DB.

    Args:
        nag_note: Short, specific description of the thing to keep after
            the user about, e.g. "renew the passport" or "email the nyu
            registrar to get reinstated".
        user_number: The user's phone number.
    """
    client = await _get_client()
    response = await (
        client.table(NAG_TABLE)
        .insert(
            {
                "user_phone_number": user_number,
                "nag_note": nag_note,
            }
        )
        .execute()
    )
    return response.data[0]


def get_nag_tool_definition() -> dict:
    """Anthropic tool definition for create_nag.

    user_number is deliberately NOT in the schema — it's injected
    programmatically from the webhook, never chosen by the model."""
    return {
        "name": "create_nag",
        "description": (
            "Record a standing nag: something the user wants to be kept "
            "after about until it's done, with no set time attached — "
            "'nag me about the passport until i renew it', 'stay on me "
            "about booking the flights'. Nags ride the daily morning "
            "rundown; they are NOT scheduled alarms. If the user wants "
            "nagging at specific times ('every 10 minutes', 'every day at "
            "3pm'), that's create_reminder or create_event territory, not "
            "this. If one message contains several distinct nags, call "
            "this once per nag, all in the same turn."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nag_note": {
                    "type": "string",
                    "description": (
                        "Short, specific, self-contained description of "
                        "the thing to keep after the user about, e.g. "
                        "'renew the passport' or 'email the nyu registrar "
                        "to get reinstated'. Enough context that the nag "
                        "still makes sense days later on its own."
                    ),
                },
            },
            "required": ["nag_note"],
        },
    }


#### FOR DEBUGGING PURPOSES ####
if __name__ == "__main__":
    async def _test():
        row = await create_nag(
            nag_note="ROUNDTRIP TEST - safe to ignore",
            user_number="+15550000000",
        )
        print("inserted:", row)
        client = await _get_client()
        await client.table(NAG_TABLE).delete().eq("id", row["id"]).execute()
        check = (
            await client.table(NAG_TABLE)
            .select("id")
            .eq("id", row["id"])
            .execute()
        )
        print("cleaned up, row gone:", check.data == [])

    asyncio.run(_test())
