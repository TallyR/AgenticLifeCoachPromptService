import asyncio

from message_api import _get_client

REMINDER_TABLE = "ReminderToolTable"

async def create_reminder(
    timezone: str,
    hour_to_be_triggered: int,
    minute_to_be_triggered: int,
    second_to_be_triggered: int,
    am_or_pm: str,
    days_of_week: list[str],
    note: str,
    number_of_occurrences: int,
    user_number: str,
) -> dict:
    """Write one reminder row to the ReminderToolTable and return it.

    `id` and `created_at` are filled in by the DB, so they are not passed here.

    Args:
        timezone: IANA timezone name, e.g. "America/New_York".
        hour_to_be_triggered: Hour on a 12-hour clock (1-12), paired with am_or_pm.
        minute_to_be_triggered: Minute (0-59).
        second_to_be_triggered: Second (0-59).
        am_or_pm: "AM" or "PM".
        days_of_week: Days the reminder fires on, e.g. ["Monday", "Wednesday"].
        note: The reminder text to send to the user.
        number_of_occurrences: How many times this reminder should fire.
        user_number: The recipient's phone number.
    """
    client = await _get_client()
    response = await (
        client.table(REMINDER_TABLE)
        .insert(
            {
                "timezone": timezone,
                "hour_to_be_triggered": hour_to_be_triggered,
                "minute_to_be_triggered": minute_to_be_triggered,
                "second_to_be_triggered": second_to_be_triggered,
                "am_or_pm": am_or_pm,
                "days_of_week": days_of_week,
                "note": note,
                "number_of_occurrences": number_of_occurrences,
                "user_number": user_number,
            }
        )
        .execute()
    )
    return response.data[0]

def get_create_reminder_tool_definition() -> dict:
    """Anthropic tool definition for create_reminder.

    user_number is deliberately NOT in the schema — it's injected
    programmatically from the webhook, never chosen by the model."""
    return {
        "name": "create_reminder",
        "description": (
            "Create a recurring reminder that gets texted to the user at a "
            "specific local time on specific days of the week. Use this when "
            "the user wants ongoing, long-term nudges — 'every tuesday at 4', "
            "'workdays at 8pm', 'remind me every morning to stretch'. The "
            "reminder fires at the given time on each listed day until it has "
            "fired number_of_occurrences times in total. The note is the text "
            "the user receives when it fires, so write it like a message from "
            "you, not a system alert."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "The user's timezone as an IANA name, e.g. "
                        "'America/New_York' or 'America/Chicago'. Infer it "
                        "from what you know about the user."
                    ),
                },
                "hour_to_be_triggered": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 12,
                    "description": "Hour on a 12-hour clock (1-12), paired with am_or_pm.",
                },
                "minute_to_be_triggered": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": (
                        "Minute (0-59). A bare hour like '8pm' means 0."
                    ),
                },
                "second_to_be_triggered": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": "Second (0-59). Almost always 0.",
                },
                "am_or_pm": {
                    "type": "string",
                    "enum": ["AM", "PM"],
                    "description": "Exactly 'AM' or 'PM'. Required.",
                },
                "days_of_week": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "Monday",
                            "Tuesday",
                            "Wednesday",
                            "Thursday",
                            "Friday",
                            "Saturday",
                            "Sunday",
                        ],
                    },
                    "minItems": 1,
                    "uniqueItems": True,
                    "description": (
                        "Days the reminder fires, spelled out exactly as in "
                        "the enum. 'every workday' means Monday through "
                        "Friday; 'every day' means all seven."
                    ),
                },
                "note": {
                    "type": "string",
                    "description": (
                        "The reminder text the user will receive when it "
                        "fires. Make it relevant to what they asked for and "
                        "fun — it's their alarm message, written in your "
                        "voice."
                    ),
                },
                "number_of_occurrences": {
                    "type": "integer",
                    "description": (
                        "Total number of times this reminder should fire. "
                        "Pick a number that fits the goal, or -1 if it "
                        "should repeat forever."
                    ),
                },
            },
            "required": [
                "timezone",
                "hour_to_be_triggered",
                "minute_to_be_triggered",
                "second_to_be_triggered",
                "am_or_pm",
                "days_of_week",
                "note",
                "number_of_occurrences",
            ],
        },
    }


#### FOR DEBUGGING PURPOSES ####
if __name__ == "__main__":
    import json

    from faro_system_prompt import FARO_SYSTEM_PROMPT
    from prompt_proc import (
        AGENT_TURN_LIMIT,
        MdType,
        _llm,
        _render_history,
        get_conversation,
        get_md,
    )

    TEST_NUMBER = "+18323346991"

    async def _run_agent_turn(messages: list, tools: list) -> None:
        """One Faro turn: call the model, execute any tool calls, feed the
        results back, repeat until it answers in plain text."""
        for _ in range(AGENT_TURN_LIMIT):
            response = await _llm.beta.messages.create(
                model="claude-fable-5",
                max_tokens=4096,
                system=FARO_SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                betas=["server-side-fallback-2026-06-01"],
                fallbacks=[{"model": "claude-opus-4-8"}],
            )

            # Append the assistant turn verbatim — this keeps the thinking
            # and tool_use blocks intact, which the API requires on replay.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                reply = next(
                    (b.text for b in response.content if b.type == "text"), ""
                )
                print(f"\nFARO: {reply}")
                return

            # Execute every tool call in the turn, then send all results
            # back in a single user message (matched by tool_use_id).
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"\n[tool call] {block.name}({json.dumps(block.input)})")
                row = await create_reminder(**block.input, user_number=TEST_NUMBER)
                print(f"[tool result] inserted row id {row['id']}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(row),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        print(f"agent loop hit its {AGENT_TURN_LIMIT}-round cap without finishing")

    async def _chat() -> None:
        """Interactive verification harness: text Faro from the terminal.
        Same context assembly as process_incoming_text, plus the reminder
        tool. Nothing is texted or saved to MessageTable — the conversation
        accumulates in memory only. Tool calls DO write real reminder rows.

        One asyncio.run for the whole session on purpose: the shared clients
        bind to the first event loop, so per-message loops would break them.
        """
        user_md, agent_md, history = await asyncio.gather(
            get_md(TEST_NUMBER, MdType.USER),
            get_md(TEST_NUMBER, MdType.AGENT),
            get_conversation(TEST_NUMBER),
        )
        preamble = (
            f"<message_history>\n{_render_history(history)}\n</message_history>\n\n"
            f"<user_notes>\n{user_md}\n</user_notes>\n\n"
            f"<agent_notes>\n{agent_md}\n</agent_notes>\n\n"
            f"The user just texted you:\n"
        )
        messages: list = []
        tools = [get_create_reminder_tool_definition()]

        print("texting Faro — empty message or Ctrl+C to quit")
        while True:
            try:
                incoming = input("\nYOU: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not incoming:
                break

            if not messages:
                # First turn carries the DB context; later turns are plain.
                messages.append({"role": "user", "content": preamble + incoming})
            else:
                messages.append({"role": "user", "content": incoming})

            await _run_agent_turn(messages, tools)

    asyncio.run(_chat())