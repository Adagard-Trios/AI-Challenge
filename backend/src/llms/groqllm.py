from langchain_groq import ChatGroq
import os
from dotenv import load_dotenv


class GroqLLM:
    def __init__(self):
        load_dotenv()

    def get_llm(self):
        try:
            self.groq_api_key = os.getenv("GROQ_API_KEY")

            llm = ChatGroq(
                api_key=self.groq_api_key,
                model="openai/gpt-oss-20b",
                streaming=False,
                temperature=0.1,
            )
            return llm

        except Exception as e:
            raise ValueError("Error initializing Groq LLM: {}".format(e))
