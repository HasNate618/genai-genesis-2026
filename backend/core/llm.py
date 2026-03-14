from google import genai
from core.config import config

client = genai.Client(api_key=config.GEMINI_API_KEY)

def generate(prompt: str, model: str = None) -> str:
    model = model or config.GEMINI_MODEL
    response = client.models.generate_content(
        model=model,
        contents=prompt
    )
    return response.text
