"""
Integrates NeMo Guardrails into the OpenAI client's chat completion process
to enforce security policies like PII redaction
and unauthorized action blocking.

It dynamically wraps the 'client.chat.completions.create' method to perform
input and output checks using the configured guardrails.
"""

import os
import re
from nemoguardrails import LLMRails, RailsConfig
import openai

_rails = None

PII_PATTERNS = {
    "USER_ACCOUNT_ID": r"\b[A-Z]\d{7,15}\b",

    "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",

    "PHONE_NUMBER": r"\b\+?1?\d{9,15}\b"
}


def check_pii(text: str = "") -> str:
    """
    Action function registered with NeMo Guardrails to scan and redact
    known PII patterns (User Account ID, Email, Phone Number) from text.
    """

    if not text:
        return ""

    try:
        cleaned_text = text
        for entity_type, pattern in PII_PATTERNS.items():
            cleaned_text = re.sub(pattern, "<REDACTED>", cleaned_text)

        return cleaned_text

    except Exception as e:
        print(f"check_pii failed: {e}")
        return text


def init_guardrails():
    """
    Initializes the global LLMRails instance from the 'guardrails_config'
    directory and registers the custom 'check_pii' action.
    """
    global _rails

    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, 'guardrails_config')

    if _rails is None:
        try:
            config = RailsConfig.from_path(config_path)
            _rails = LLMRails(config)

            _rails.register_action(check_pii, "check_pii")

        except Exception as e:
            print(f"Failed to initialize Guardrails: {e}")


def _sanitize_messages(messages):
    """
    Prepares a list of message dictionaries for NeMo Guardrails by ensuring
    all messages have a non-None 'content' field, which is required by NeMo.
    """

    clean_messages = []
    for msg in messages:
        msg_copy = msg.copy()
        if "content" not in msg_copy or msg_copy["content"] is None:
            msg_copy["content"] = ""
        clean_messages.append(msg_copy)
    return clean_messages


def apply_guardrails_to_openai_client(client: openai.OpenAI):
    """
    Wraps the 'client.chat.completions.create' method with a guarded function
    to apply NeMo Guardrails to both user input and assistant output.
    """
    global _rails
    if _rails is None:
        return

    original_create = client.chat.completions.create

    def guarded_create(*args, **kwargs):
        raw_messages = kwargs.get("messages", [])
        is_streaming = kwargs.get("stream", False)

        nemo_messages = _sanitize_messages(raw_messages)

        user_input = next(
            (m["content"] for m in reversed(nemo_messages)
             if m["role"] == "user"),
            None
        )

        if user_input:
            res = _rails.generate(messages=nemo_messages)

            content = ""
            if isinstance(res, dict):
                content = res.get("content", "")
            elif hasattr(res, "content"):
                content = res.content

            if "I cannot modify, update, or delete data" in content:
                from types import SimpleNamespace
                blocked_msg = "Guardrails blocked: " + content
                if is_streaming:
                    def blocking_generator():
                        yield SimpleNamespace(choices=[SimpleNamespace(
                            delta=SimpleNamespace(content=blocked_msg))])
                    return blocking_generator()
                else:
                    return SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(
                            content=blocked_msg, role="assistant",
                            tool_calls=None))])

        response = original_create(*args, **kwargs)

        if not is_streaming and hasattr(response, 'choices'):
            try:
                choice = response.choices[0]
                original_text = choice.message.content

                if original_text:
                    pii_check = _rails.generate(
                        messages=[{"role": "assistant",
                                   "content": original_text}],
                        options={"output_rails": True}
                    )

                    if pii_check:
                        clean_content = None
                        if isinstance(pii_check, dict):
                            clean_content = pii_check.get("content")
                        elif hasattr(pii_check, "content"):
                            clean_content = pii_check.content

                        if clean_content:
                            choice.message.content = clean_content
            except Exception as e:
                print(f"PII Check warning: {e}")

        return response

    client.chat.completions.create = guarded_create
