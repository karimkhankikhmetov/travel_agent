"""
main.py -- chat with Travel Buddy in the terminal.

Run:  python main.py

Commands inside the chat:
  /card      turn the last answer into a structured trip card (Pydantic)
  /ideas     suggest 3 follow-up questions for the last answer
  /new       start a fresh conversation (clears memory)
  /exit      quit
"""

import uuid

from agent import ask, build_agent_with_memory, build_card_chain, build_followup_chain, build_llm


def main() -> None:
    llm = build_llm()
    agent = build_agent_with_memory(llm)
    card_chain = build_card_chain(llm)
    followup_chain = build_followup_chain(llm)

    home_city = input("Your home city [Almaty]: ").strip() or "Almaty"
    session_id = str(uuid.uuid4())
    last_question, last_answer = "", ""

    print("\nTravel Buddy is ready. Type /exit to quit, /card, /ideas, /new.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue

        if text == "/exit":
            break
        if text == "/new":
            session_id = str(uuid.uuid4())
            last_question, last_answer = "", ""
            print("Memory cleared.\n")
            continue
        if text == "/card":
            if not last_answer:
                print("Ask something first.\n")
                continue
            card = card_chain.invoke({"answer": last_answer})
            print(card.model_dump_json(indent=2), "\n")
            continue
        if text == "/ideas":
            if not last_answer:
                print("Ask something first.\n")
                continue
            print(followup_chain.invoke({"question": last_question, "answer": last_answer}), "\n")
            continue

        try:
            answer = ask(agent, text, session_id=session_id, home_city=home_city)
        except Exception as exc:  # network, rate limit, bad key ...
            print(f"Sorry, something went wrong: {type(exc).__name__}: {exc}\n")
            continue
        last_question, last_answer = text, answer
        print(f"\nTravel Buddy: {answer}\n")


if __name__ == "__main__":
    main()
