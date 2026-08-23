import asyncio

from message_api import _get_client

USER_SETTINGS_TABLE = "UserSettingsTable"


async def create_user_setting(setting_note: str, user_number: str) -> dict:
    """Write one user-setting note to the UserSettingsTable and return the row.

    A setting note is a durable fact about how the user wants Faro to work:
    their name, country, grammar/capitalization preference, what they're
    using Faro for, etc. Many rows per user; newer notes win on conflict.
    `id` and `created_at` are filled in by the DB.

    NB: this table's column is phone_number (not user_number like the
    reminder/event tables).
    """
    client = await _get_client()
    response = await (
        client.table(USER_SETTINGS_TABLE)
        .insert(
            {
                "phone_number": user_number,
                "setting_note": setting_note,
            }
        )
        .execute()
    )
    return response.data[0]


async def get_user_settings(user_number: str) -> str:
    """All setting notes for this number, formatted for the prompt context.

    Oldest first, so when notes conflict the later line is the current
    preference. Returns "NONE" when there are no settings yet (expected for
    users from before the settings tool existed — the transition phase).
    """
    client = await _get_client()
    response = await (
        client.table(USER_SETTINGS_TABLE)
        .select("*")
        .eq("phone_number", user_number)
        .order("created_at")
        .execute()
    )
    lines = [f"* id={row['id']}: {row['setting_note']}" for row in response.data]
    return "\n".join(lines) if lines else "NONE"


def get_user_settings_tool_definition() -> dict:
    """Anthropic tool definition for create_user_setting.

    user_number is deliberately NOT in the schema — it's injected
    programmatically from the webhook, never chosen by the model."""
    return {
        "name": "create_user_setting",
        "description": (
            "Record one durable note about how the user wants you to work: "
            "their name, their country, a grammar/capitalization preference, "
            "what they're using you for, and the like. Call it whenever the "
            "user states or changes such a preference — and also when you "
            "spot one in the message history that isn't in <user_settings> "
            "yet (older users predate this tool, so their preferences may "
            "only live in history; backfill them as you notice). One note "
            "per setting. To change a setting, record a new note stating "
            "the current preference — newer notes win."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "setting_note": {
                    "type": "string",
                    "description": (
                        "Short, self-contained statement of the setting, "
                        "e.g. 'name: hassan', 'wants proper grammar and "
                        "capitalization', 'uses faro mainly for gym "
                        "accountability'."
                    ),
                },
            },
            "required": ["setting_note"],
        },
    }


#### FOR DEBUGGING PURPOSES ####
if __name__ == "__main__":
    async def _test():
        row = await create_user_setting(
            setting_note="ROUNDTRIP TEST - safe to ignore",
            user_number="+18323346991",
        )
        print("inserted:", row)
        print("rendered:\n", await get_user_settings("+18323346991"))
        client = await _get_client()
        await client.table(USER_SETTINGS_TABLE).delete().eq("id", row["id"]).execute()
        print("cleaned up")

    asyncio.run(_test())
