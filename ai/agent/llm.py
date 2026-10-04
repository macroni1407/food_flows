"""Plain Groq calls used inside the tools (the agent loop itself uses langchain-openai)."""
import json
import time

from groq import Groq

from . import settings

_client = None


def _groq():
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def _with_retries(call, attempts=3):
    for attempt in range(attempts):
        try:
            return call()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def chat_json(system, user, model=None):
    """Ask for a JSON object; returns the parsed dict."""
    response = _with_retries(lambda: _groq().chat.completions.create(
        model=model or settings.SQL_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    ))
    return json.loads(response.choices[0].message.content)


def chat_text(system, user, model=None):
    response = _with_retries(lambda: _groq().chat.completions.create(
        model=model or settings.ANSWER_MODEL,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    ))
    return response.choices[0].message.content
