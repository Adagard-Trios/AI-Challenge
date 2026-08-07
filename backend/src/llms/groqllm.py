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
            )
            return llm

        except Exception as e:
            raise ValueError("Error initializing Groq LLM: {}".format(e))
