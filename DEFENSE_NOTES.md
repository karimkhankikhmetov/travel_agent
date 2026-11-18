# Defense notes (read this before the defense)

Code explanation is 25 points and LangChain parts are 25 points. Half of your grade is you explaining the code, so read this twice and open each file while you read.

Say it in English. It gives a higher maximum (100 vs 90).

---

## 1. The big picture in 30 seconds

> "My agent is called Travel Buddy. The LLM is the brain. It reads the user's question and decides what to do. My 7 tools are its hands: they get live weather, exchange rates, country facts, do exact math and save files. LangChain connects them in a loop: the LLM asks for a tool, my code runs it, the result goes back to the LLM, and the LLM writes the final answer."

---

## 2. Step by step: what happens when the user types a question

Example: "Tomorrow I want to hike near Almaty. What should I pack?"

1. `main.py` calls `ask(...)` in `agent.py`.
2. `RunnableWithMessageHistory` loads the old messages of this `session_id` (memory).
3. The prompt is built: system rules + old messages + the new question + an empty scratchpad.
4. The LLM reads it and answers **not with text, but with a tool call**: `get_weather_forecast(city="Almaty", days=2)`.
5. `AgentExecutor` runs that Python function and gets JSON back.
6. The JSON goes into the **scratchpad** and the LLM is called again.
7. The LLM sees rain in the data and calls `get_packing_list(...)`.
8. Again the result goes to the scratchpad. The LLM now has all it needs and writes the **final answer** as normal text.
9. `AgentExecutor` stops the loop and returns it. Memory saves the question and the answer.

The loop is in `AgentExecutor`. It stops when the LLM answers with text instead of a tool call, or after `max_iterations=8` (safety).

---

## 3. How does the LLM decide which tool to call?

- LangChain sends the LLM a list of all tools: **name, description (docstring), and argument names/types**. This is built from the `@tool` function automatically.
- The LLM was trained to answer with a structured "tool call" when a tool fits. It matches the user's words to the tool descriptions.
- The LLM **never runs code**. It only says "please call this tool with these arguments". My code runs it.
- That is why docstrings matter: for example `get_weather_forecast` says "Use this whenever the user asks about weather, rain...". The system prompt also has explicit rules ("ALWAYS call get_weather_forecast, never guess").

---

## 4. How does memory work?

- LLMs have no memory. Every call starts from zero.
- `RunnableWithMessageHistory` fixes this: before each call it takes the old messages from `InMemoryChatMessageHistory` and puts them in the `chat_history` placeholder. After the call it saves the new question and answer.
- `session_id` separates conversations. `/new` makes a new id = empty memory.
- Limit: it is stored in RAM, so it disappears when the program closes. Also, a long chat means more tokens.
- Example: "What currency do they use there?" works because the history says "there" = Istanbul.

(LangChain shows a deprecation warning for this class and recommends LangGraph persistence. It still works. If asked: "I used `RunnableWithMessageHistory` because the assignment asks for it.")

---

## 5. The prompts (`prompts.py`)

- **System prompt**: role (who it is), rules (when to use which tool, what to do on errors, ask a clarifying question), answer style (verdict first, bullets, under 150 words). The date is inserted with `.partial(today=...)` because LLMs do not know today's date.
- **User prompt template** (`ChatPromptTemplate`): `Traveler's home city: {home_city}` + `Question: {input}`. I pass the home city every turn so "my budget" is in the right currency.
- `MessagesPlaceholder("chat_history")` = where memory goes.
- `MessagesPlaceholder("agent_scratchpad")` = where the tool calls and results of the current question go. **The agent needs this placeholder, or it will not work.**

---

## 6. LCEL chains and structured output

LCEL = LangChain Expression Language. The `|` pipe connects steps: output of the left side is input of the right side.

- `CARD_PROMPT | llm.with_structured_output(TripCard)`: the LLM is forced to answer in the shape of my Pydantic class `TripCard` (destination, verdict, packing list...). The result is a Python object, not text.
- `FOLLOWUP_PROMPT | llm | StrOutputParser()`: prompt → LLM → parser that turns the LLM message into a plain string.
- The agent itself is also a chain: `prompt | llm | tool-calling output parser`, wrapped in `AgentExecutor`.

---

## 7. Why this model and these choices

- Gemini 2.5 Flash (or whatever you use): free API key, good at tool calling, fast. Replace this with the model you really used.
- `ChatOpenAI` with `base_url`: one code works with Gemini, Groq, OpenAI, because they all copy the OpenAI API format.
- `temperature=0`: for tool use I want stable, predictable choices, not creative ones.
- Own-logic tools (budget, packing): LLMs are bad at exact math, so code does the math.
- Frankfurter + fallback: Frankfurter (ECB) does not have KZT, so if it fails, the tool uses open.er-api.com. It matters because I am in Kazakhstan.

---

## 8. Error handling (20 points for tools)

Every tool: `try/except`, timeout of 10 seconds, returns `{"error": "..."}`. The LLM reads the error and tells the user. Show this in the defense: ask for the weather of "Atlantisville123".

---

## 9. LangSmith

- It records every step: the prompt, each tool call with its arguments and result, the final answer, tokens and time.
- It turns on with `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`. No code changes needed, LangChain sends the traces by itself.
- Open smith.langchain.com → your project `travel-buddy-assignment-3` → click a run → show the tool call steps.

---

## 10. Questions the teacher may ask (short answers)

- **What is the scratchpad?** Temporary space for the tool calls and results of the current question.
- **What if the LLM calls a tool that does not exist?** `AgentExecutor` returns an error message to the LLM and it tries again. `handle_parsing_errors=True` and `max_iterations=8` prevent crashes and endless loops.
- **Why are the tools returning JSON strings?** The LLM reads text. JSON is clear and has field names.
- **Why `@tool` needs type hints and docstring?** LangChain builds the tool schema from them, and the LLM reads it.
- **What is the difference between the agent and a simple chain?** A chain has fixed steps. An agent decides the steps at runtime (which tool, how many times).
- **How do you stop the LLM from making things up?** Rules in the system prompt + real data from tools + the instruction to report errors honestly.
- **What would you improve?** Save memory to a database, add flight search with SerpAPI, stream the answer, add tests.

---

## 11. Before the defense: your checklist

1. Run the project once. Check the answers are correct.
2. Run `python run_examples.py` and paste `examples.md` into the README.
3. Make LangSmith screenshots and add them to the README.
4. Write your real model name in the README.
5. Push to GitHub (without `.env`) and submit **before** the defense. Be ready to show the submission box.
6. Open each file once and read the comments, so nothing in the code is new to you.
