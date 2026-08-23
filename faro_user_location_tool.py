import asyncio

from message_api import _get_client

USER_LOCATION_TABLE = "UserLocationTable"


async def set_user_timezone(location_note: str, user_number: str) -> dict:
    """Save (or overwrite) this user's single location record.

    user_number is the table's primary key, so this upserts: one row per
    user, setting again replaces the old note. The note carries the place
    plus the IANA timezone inferred from it, e.g.
    "new york city — America/New_York".
    """
    client = await _get_client()
    response = await (
        client.table(USER_LOCATION_TABLE)
        .upsert(
            {
                "user_number": user_number,
                "location_note": location_note,
            },
            on_conflict="user_number",
        )
        .execute()
    )
    return response.data[0]


async def get_user_timezone(user_number: str) -> dict:
    """Read this user's saved location record.

    Returns {"location_note": <note>} when set. When there's no record yet
    (users from before this tool existed — the transition phase), returns
    location_note None plus a hint to check the message history or ask.
    """
    client = await _get_client()
    response = await (
        client.table(USER_LOCATION_TABLE)
        .select("*")
        .eq("user_number", user_number)
        .execute()
    )
    if response.data:
        return {"location_note": response.data[0]["location_note"]}
    return {
        "location_note": None,
        "note": (
            "no location on record yet. check the message history for a "
            "city, or ask the user; then save it with set_user_timezone."
        ),
    }


def get_user_timezone_tool_definition() -> dict:
    """Anthropic tool definition for get_user_timezone. Takes no model
    inputs — user_number is injected programmatically."""
    return {
        "name": "get_user_timezone",
        "description": (
            "Look up the user's saved location and timezone (their city "
            "plus the IANA zone). Call this before scheduling anything when "
            "the timezone isn't already clear from this conversation. If it "
            "comes back empty, the user may predate this record: check the "
            "message history for a city they've mentioned, and if you find "
            "one, save it with set_user_timezone; if you don't, ask for "
            "their city."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }


def get_set_user_timezone_tool_definition() -> dict:
    """Anthropic tool definition for set_user_timezone.

    user_number is deliberately NOT in the schema — it's injected
    programmatically from the webhook, never chosen by the model."""
    return {
        "name": "set_user_timezone",
        "description": (
            "Save the user's location: their city or place plus the IANA "
            "timezone you infer from it, e.g. 'new york city — "
            "America/New_York'. One record per user; saving again "
            "overwrites, so also use this when they move or correct you, "
            "and to backfill when their city appears in the message history "
            "but get_user_timezone comes back empty. Keep the note short: "
            "place, then zone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_note": {
                    "type": "string",
                    "description": (
                        "The place plus its IANA timezone, e.g. 'houston — "
                        "America/Chicago' or 'london — Europe/London'."
                    ),
                },
            },
            "required": ["location_note"],
        },
    }


#### FOR DEBUGGING PURPOSES ####
if __name__ == "__main__":
    async def _test():
        print("before:", await get_user_timezone("+18323346991"))
        await set_user_timezone(
            location_note="ROUNDTRIP TEST - safe to ignore",
            user_number="+18323346991",
        )
        print("after set:", await get_user_timezone("+18323346991"))
        client = await _get_client()
        await client.table(USER_LOCATION_TABLE).delete().eq(
            "user_number", "+18323346991"
        ).execute()
        print("cleaned up:", await get_user_timezone("+18323346991"))

    asyncio.run(_test())
