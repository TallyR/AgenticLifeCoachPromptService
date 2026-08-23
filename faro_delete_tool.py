import asyncio
from enum import Enum

from message_api import _get_client


class DeleteType(Enum):
    """Which table to delete from. Each member carries its table name."""

    REMINDER = "ReminderToolTable"
    EVENT = "EventToolTable"
    NAG = "DailyNagTable"
    SETTING = "UserSettingsTable"
    LOCATION = "UserLocationTable"

    def __init__(self, table: str):
        self.table = table


async def delete_entry(
    row_id: int, delete_type: DeleteType, user_number: str | None = None
) -> bool:
    """Delete one reminder, event, nag, or user setting by id — or the
    user's location record.

    Used instead of edits, when the user just wants an entry gone, and for
    nags it's also how one gets crossed off once it's done. Quietly no-ops
    if the row doesn't exist. Returns True if a row was deleted, False if
    nothing matched.

    LOCATION is the odd one out: UserLocationTable has no id column (its
    primary key is the user), so row_id is ignored and user_number is
    required for it.
    """
    client = await _get_client()
    if delete_type is DeleteType.LOCATION:
        if user_number is None:
            raise ValueError("deleting a LOCATION requires user_number")
        response = await (
            client.table(delete_type.table)
            .delete()
            .eq("user_number", user_number)
            .execute()
        )
        label = f"for {user_number}"
    else:
        response = await (
            client.table(delete_type.table)
            .delete()
            .eq("id", row_id)
            .execute()
        )
        label = f"id {row_id}"

    if response.data:
        print(f"deleted {delete_type.name} {label}")
        return True

    print(f"no {delete_type.name} {label} — nothing deleted")
    return False


def get_delete_entry_tool_definition() -> dict:
    """Anthropic tool definition for delete_entry.

    The schema's delete_type enum is built from DeleteType, so adding a new
    member there automatically shows up here."""
    return {
        "name": "delete_entry",
        "description": (
            "Delete one reminder, event, nag, or user setting by its row id — "
            "or the user's saved location. Use this when the user wants an "
            "entry gone, and also to CHANGE one: there is no editing tool, so "
            "to modify an existing entry you must delete it and recreate it "
            "with the corrected values via the matching create tool. For a "
            "NAG, deleting is also how you cross it off the moment the user "
            "says it's done. For a SETTING, delete a note that's outdated or "
            "was recorded wrong (though usually just recording a newer note "
            "is enough — newer wins). For LOCATION, row_id is ignored (the "
            "record is keyed to the user, pass 0) — prefer set_user_timezone "
            "to correct a location; only delete it if the user asks you to "
            "forget where they live. Deleting something that doesn't exist "
            "is safe: nothing happens and the result says nothing matched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "row_id": {
                    "type": "integer",
                    "description": (
                        "The id of the row to delete — the 'id' field "
                        "returned when the entry was created, also shown in "
                        "the context blocks. For LOCATION there is no id: "
                        "pass 0, it's ignored."
                    ),
                },
                "delete_type": {
                    "type": "string",
                    "enum": [member.name for member in DeleteType],
                    "description": (
                        "Which kind of entry to delete: REMINDER (recurring), "
                        "EVENT (one-off), NAG (standing keep-after-me item), "
                        "SETTING (a user-settings note), or LOCATION (the "
                        "user's saved city/timezone record). Must match what "
                        "the entry was created as."
                    ),
                },
            },
            "required": ["row_id", "delete_type"],
        },
    }


#### FOR DEBUGGING PURPOSES ####
if __name__ == "__main__":
    async def _test():
        # Deleting an id that doesn't exist: quiet fail, prints, returns False.
        result = await delete_entry(14, DeleteType.EVENT)
        print("returned:", result)

        result = await delete_entry(6, DeleteType.REMINDER)
        print("returned:", result)

    asyncio.run(_test())
