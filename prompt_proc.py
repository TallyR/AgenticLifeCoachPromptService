# this is where prompts are processed

# Have a raw prompt text....

# Query conversation history, agent note, user note to gather context

from message_api import TABLE, _get_client

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
    print(asyncio.run(get_conversation("+18323346991")))
