from langchain_groq import ChatGroq
import os
from dotenv import load_dotenv


class GroqLLM:
    def __init__(self):
        load_dotenv()

    def get_llm(self):
        try:
            self.groq_api_key = os.getenv("GROQ_API_KEY")

            # Not hardcoded: see src/llms/models.py. The chatbot's model was
            # pinned here-style and silently stopped existing.
            from .models import agent_model

            llm = ChatGroq(
                api_key=self.groq_api_key,
                model=agent_model(),
                streaming=False,
                temperature=0.1,
                # Explicit, because agent_model() is a REASONING model: it
                # spends output budget thinking before it writes a token of
                # the answer. With no limit set the default was low enough
                # that a 12-post classification batch was truncated mid-JSON,
                # and the whole batch came back unclassified -- no severity,
                # no entities, and entities are what relevance scoring joins
                # on.
                #
                # Not larger: Groq's free tier is 8,000 tokens per MINUTE
                # shared across five domain calls per cycle, so a generous
                # per-call ceiling is how you trade one failure mode for a
                # 413. The parser also salvages truncated arrays, so this is
                # the first line of defence rather than the only one.
                max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "3000")),
            )
            return llm

        except Exception as e:
            raise ValueError("Error initializing Groq LLM: {}".format(e))
