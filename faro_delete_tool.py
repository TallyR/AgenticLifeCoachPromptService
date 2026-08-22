import asyncio
from enum import Enum

from message_api import _get_client


class DeleteType(Enum):
    """Which table to delete from. Each member carries its table name."""

    REMINDER = "ReminderToolTable"
    EVENT = "EventToolTable"
    NAG = "DailyNagTable"

    def __init__(self, table: str):
        self.table = table


async def delete_entry(row_id: int, delete_type: DeleteType) -> bool:
    """Delete one reminder, event, or nag by id.

    Used instead of edits, when the user just wants an entry gone, and for
    nags it's also how one gets crossed off once it's done. Quietly no-ops
    if the row doesn't exist. Returns True if a row was deleted, False if
    nothing matched.
    """
    client = await _get_client()
    response = await (
        client.table(delete_type.table)
        .delete()
        .eq("id", row_id)
        .execute()
    )
    if response.data:
        print(f"deleted {delete_type.name} id {row_id}")
        return True

    print(f"no {delete_type.name} with id {row_id} — nothing deleted")
    return False


def get_delete_entry_tool_definition() -> dict:
    """Anthropic tool definition for delete_entry.

    The schema's delete_type enum is built from DeleteType, so adding a new
    member there automatically shows up here."""
    return {
        "name": "delete_entry",
        "description": (
            "Delete one reminder, event, or nag by its row id. Use this when "
            "the user wants an entry gone — and also to CHANGE one: there is "
            "no editing tool, so to modify an existing entry you must delete "
            "it with this tool and then recreate it with the corrected values "
            "via create_reminder, create_event, or create_nag. For a NAG, "
            "deleting is also how you cross it off: the moment the user says "
            "that thing is done or tells you to stop nagging, delete the nag. "
            "The id is the 'id' field returned when the entry was created. "
            "Deleting an id that doesn't exist is safe: nothing happens and "
            "the result says nothing matched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "row_id": {
                    "type": "integer",
                    "description": (
                        "The id of the row to delete — the 'id' field "
                        "returned when the reminder or event was created."
                    ),
                },
                "delete_type": {
                    "type": "string",
                    "enum": [member.name for member in DeleteType],
                    "description": (
                        "Which kind of entry to delete: REMINDER (recurring), "
                        "EVENT (one-off), or NAG (standing keep-after-me "
                        "item). Must match what the entry was created as."
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
