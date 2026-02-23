from __future__ import annotations
import os 
from typing import Any 
from langchain_core.language_models.chat_models import BaseChatModel

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from dotenv import load_dotenv
load_dotenv()
def get_llm() -> BaseChatModel: 
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model = os.getenv("LLM_MODEL" , "gpt-4o-mini")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    if provider == "openai":
        return ChatOpenAI(model =model,temperature = temperature)
    if provider == "google":
        return ChatGoogleGenerativeAI(model= model, temperature =temperature)
    if provider == "ollama":
        return ChatOllama(model = model,temperature =temperature)
    

    raise ValueError(f"Unknown lLM_provider: {provider}")

