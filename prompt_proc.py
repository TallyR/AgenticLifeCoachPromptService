# this is where prompts are processed

# Have a raw prompt text....

# Query conversation history, agent note, user note to gather context

from enum import Enum

from message_api import TABLE, _get_client


class MdType(Enum):
    """Which markdown table to read. Each carries its (table, field) pair."""
    USER = ("UserMdTable", "user_md")
    AGENT = ("AgentMdTable", "agent_md")

    def __init__(self, table: str, field: str):
        self.table = table
        self.field = field


async def get_md(phone_number: str, md_type: MdType) -> str:
    """Get the md text for a phone number from the USER or AGENT table. If none
    exists, create a row with the md field = "EMPTY" and return that text."""
    client = await _get_client()
    response = await (
        client.table(md_type.table)
        .select("*")
        .eq("phone_number", phone_number)
        .execute()
    )
    if response.data:
        return response.data[0][md_type.field]

    inserted = await (
        client.table(md_type.table)
        .insert({"phone_number": phone_number, md_type.field: "EMPTY"})
        .execute()
    )
    return inserted.data[0][md_type.field]


async def set_md(phone_number: str, md_type: MdType, text: str) -> str:
    """Set the md text for a phone number in the USER or AGENT table, creating
    the row if it doesn't exist yet. Returns the saved text."""
    client = await _get_client()
    updated = await (
        client.table(md_type.table)
        .update({md_type.field: text})
        .eq("phone_number", phone_number)
        .execute()
    )
    if updated.data:
        return updated.data[0][md_type.field]

    inserted = await (
        client.table(md_type.table)
        .insert({"phone_number": phone_number, md_type.field: text})
        .execute()
    )
    return inserted.data[0][md_type.field]


async def get_conversation(phone_number: str) -> list[dict]:
    """Return every message to or from `phone_number`, oldest first (by sent_at)."""
    client = await _get_client()
    response = await (
        client.table(TABLE)
        .select("*")
        .or_(
            f"from_phone_number.eq.{phone_number},"
            f"to_phone_number.eq.{phone_number}"
        )
        .order("sent_at")
        .execute()
    )
    return response.data

# Query the agent note text

# Query the user note text

# Have the model play a role. 
    # my goal is to be agent that helps you accomplish your goals keeps you
        # from psycologically looping and checks in you to make sure you are on the right path. 
        # digital therapist that helps you stop negative thought patterns that you can text at anytime
        # like a digital therapist you can talk to and will check in you all the time!
# Have the model have a response.
# Have the model decide whether or not to edit the user.md file
# Have the model decide whether or not to edit the agent.md file
# (so much agent tools could be built here!)

# Need to reset the DB and double check this is working
if __name__ == "__main__":
    import asyncio
    async def main():
        print(await get_md("+18323346991", MdType.USER))
        print(await set_md("+18323346993", MdType.USER, "He's pretty potatoe"))
    asyncio.run(main())
