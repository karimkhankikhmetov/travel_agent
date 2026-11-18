"""
agent.py -- builds the LLM, the agent, the memory and the two LCEL chains.

Flow for one question:
  user question
    -> RunnableWithMessageHistory   (loads old messages for this session)
    -> AgentExecutor                (the loop)
         -> prompt | llm            (LLM reads rules + history + question)
         -> LLM answers "call tool X with args Y"
         -> AgentExecutor runs the tool, adds the result to the scratchpad
         -> LLM reads the result, calls another tool OR writes the final answer
    -> final answer (saved to memory)
"""

import os
from typing import Optional

from dotenv import load_dotenv
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# AgentExecutor / create_tool_calling_agent live in `langchain` 0.3.x.
# In LangChain 1.x they moved to `langchain_classic`, so we support both.
try:
    from langchain.agents import AgentExecutor, create_tool_calling_agent
except ImportError:  # pragma: no cover
    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent

from prompts import CARD_PROMPT, FOLLOWUP_PROMPT, build_agent_prompt
from tools import ALL_TOOLS

# Load .env BEFORE anything reads os.environ.
# LangSmith tracing turns on automatically if LANGSMITH_TRACING=true is in .env.
load_dotenv()


# ---------------------------------------------------------------------------
# LLM (any OpenAI-compatible API: Gemini, Groq, OpenRouter, GitHub Models, OpenAI...)
# ---------------------------------------------------------------------------

def build_llm() -> ChatOpenAI:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is missing. Copy .env.example to .env and fill it in.")
    return ChatOpenAI(
        base_url=os.getenv("LLM_BASE_URL") or None,
        api_key=api_key,
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        temperature=0,       # 0 = stable, less random tool choices
        max_retries=2,       # retry on temporary API errors / rate limits
    )


# ---------------------------------------------------------------------------
# Agent + memory
# ---------------------------------------------------------------------------

# Memory: one chat history object per session_id, kept in RAM.
_session_store: dict[str, InMemoryChatMessageHistory] = {}


def get_session_history(session_id: str) -> InMemoryChatMessageHistory:
    if session_id not in _session_store:
        _session_store[session_id] = InMemoryChatMessageHistory()
    return _session_store[session_id]


def build_agent_with_memory(llm: Optional[ChatOpenAI] = None) -> RunnableWithMessageHistory:
    llm = llm or build_llm()
    prompt = build_agent_prompt()

    # The "brain + prompt" part: it decides which tool to call.
    agent = create_tool_calling_agent(llm, ALL_TOOLS, prompt)

    # The "loop" part: runs the tools the LLM asks for and feeds results back.
    executor = AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        max_iterations=8,              # safety: stop endless tool loops
        handle_parsing_errors=True,    # do not crash on a bad LLM output
        verbose=os.getenv("AGENT_VERBOSE", "false").lower() == "true",
    )

    # Memory wrapper: before each call it loads the old messages into
    # {chat_history}; after each call it saves the new question and answer.
    return RunnableWithMessageHistory(
        executor,
        get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )


def ask(agent_with_memory, question: str, session_id: str = "default", home_city: str = "Almaty") -> str:
    """Send one question to the agent and return the final text answer."""
    result = agent_with_memory.invoke(
        {"input": question, "home_city": home_city},
        config={
            "configurable": {"session_id": session_id},
            "run_name": "travel_buddy_turn",
            "tags": ["travel-buddy", "assignment-3"],
            "metadata": {"session_id": session_id},
        },
    )
    return result["output"]


# ---------------------------------------------------------------------------
# LCEL chains: prompt | llm | parser
# ---------------------------------------------------------------------------

class TripCard(BaseModel):
    """Structured summary of the assistant's answer."""
    destination: Optional[str] = Field(None, description="City or place the answer is about")
    verdict: str = Field(description="One-sentence conclusion, e.g. 'Good for hiking' or 'Bring a raincoat'")
    outdoor_friendly: Optional[bool] = Field(None, description="True if the weather is good for outdoor plans")
    temp_range_c: Optional[str] = Field(None, description="Temperature range like '8 to 17'")
    packing_list: list[str] = Field(default_factory=list, description="Items to pack")
    estimated_total_cost: Optional[str] = Field(None, description="Total cost with currency, if mentioned")


def build_card_chain(llm: Optional[ChatOpenAI] = None):
    """Chain 1: prompt | llm.with_structured_output(Pydantic)  -> TripCard object."""
    llm = llm or build_llm()
    return CARD_PROMPT | llm.with_structured_output(TripCard)


def build_followup_chain(llm: Optional[ChatOpenAI] = None):
    """Chain 2: prompt | llm | StrOutputParser -> plain string with 3 questions."""
    llm = llm or build_llm()
    return FOLLOWUP_PROMPT | llm | StrOutputParser()
