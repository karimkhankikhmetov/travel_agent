"""
run_examples.py -- runs 3 example conversations and saves them to examples.md.
Use this to get the "3 example conversations" and LangSmith traces for the README.

Run:  python run_examples.py
"""

from agent import ask, build_agent_with_memory, build_card_chain, build_llm

CONVERSATIONS = {
    "Example 1: Weekend hike (weather tool + packing tool)": [
        "Tomorrow I want to hike near Almaty. Is it a good idea? What should I pack?",
    ],
    "Example 2: Multi-message trip to Istanbul (follow-ups use memory)": [
        "I am thinking about a 5-day trip to Istanbul. What is the weather like for the next days?",
        "What currency do they use there and how much is 300 USD in it?",
        "OK. Hotel 60 USD per night, food 25 USD per day, transport 8 USD per day, "
        "museums 70 USD total. How much will the whole trip cost? Also give it in KZT.",
        "Great, save this plan to a file called istanbul_trip.",
    ],
    "Example 3: Place + country facts, and an error case": [
        "Tell me about Cappadocia and which country it is in, with the languages spoken there.",
        "What is the weather in Atlantisville123 tomorrow?",
    ],
}


def main() -> None:
    llm = build_llm()
    card_chain = build_card_chain(llm)
    lines = ["# Example conversations\n"]

    for title, messages in CONVERSATIONS.items():
        agent = build_agent_with_memory(llm)   # fresh memory per conversation
        session_id = title
        lines.append(f"\n## {title}\n")
        last_answer = ""
        for message in messages:
            print(f"\nUSER: {message}")
            answer = ask(agent, message, session_id=session_id, home_city="Almaty")
            print(f"AGENT: {answer}")
            lines.append(f"**User:** {message}\n\n**Agent:** {answer}\n")
            last_answer = answer

        # Show the structured output (Pydantic) once per conversation.
        card = card_chain.invoke({"answer": last_answer})
        lines.append("Structured card (`with_structured_output`):\n")
        lines.append(f"```json\n{card.model_dump_json(indent=2)}\n```\n")

    with open("examples.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\nSaved examples.md")


if __name__ == "__main__":
    main()
