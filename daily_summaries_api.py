from message_api import _get_client

ENABLED_DAILY_SUMMARIES_TABLE = "EnabledDailySummaries"


async def enable_daily_summaries(phone_number: str) -> None:
    """Mark this number as active for the daily summary. Upserts enabled=true:
    creates the row if it's a new number, flips it back on if it exists.
    Idempotent — safe (and intended) to call on every inbound message, so any
    message the user sends counts as them being active again.

    phone_number is the table's primary key, so on_conflict targets it: one
    row per number, no duplicates.
    """
    client = await _get_client()
    await (
        client.table(ENABLED_DAILY_SUMMARIES_TABLE)
        .upsert(
            {"phone_number": phone_number, "enabled": True},
            on_conflict="phone_number",
        )
        .execute()
    )
