"""Client interface for OpenAI-compatible LLM endpoints (e.g. Local AI Router / LiteLLM)."""

import json
from typing import Any, Type, TypeVar
import httpx
from pydantic import BaseModel
from research_engine.config import LLMConfig

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base exception for LLM provider errors."""
    pass


class LLMConnectionError(LLMError):
    """Raised when LLM service is unreachable."""
    pass


class LLMClient:
    """Interacts with OpenAI-compatible chat completion endpoints with structured output parsing."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.api_key = config.api_key
        self.model = config.model
        self.timeout = config.timeout_seconds

    def check_health(self) -> bool:
        """Check if LLM service is reachable."""
        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{self.base_url}/models")
                return res.status_code == 200
        except Exception:
            return False

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        temperature: float = 0.2,
    ) -> T:
        """Generate structured response conforming to a Pydantic schema."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Request json schema output format if supported, with explicit prompt instruction fallback
        schema_json = json.dumps(response_model.model_json_schema())
        augmented_system = (
            f"{system_prompt}\n\n"
            "You MUST respond ONLY with valid JSON conforming to the following JSON Schema. "
            "Do NOT include markdown formatting, backticks, or explanatory commentary outside the JSON.\n"
            f"SCHEMA:\n{schema_json}"
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": augmented_system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise LLMConnectionError(f"Failed to connect to LLM endpoint at {url}: {exc}") from exc
        except Exception as exc:
            raise LLMError(f"HTTP error during LLM call: {exc}") from exc

        if response.status_code != 200:
            raise LLMError(
                f"LLM request failed with HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            # Clean markdown codeblocks if model wrapped output in ```json ... ```
            clean_content = content.strip()
            if clean_content.startswith("```"):
                lines = clean_content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_content = "\n".join(lines).strip()

            parsed_dict = json.loads(clean_content)
            return response_model.model_validate(parsed_dict)
        except Exception as exc:
            raise LLMError(f"Failed to parse LLM structured output: {exc}") from exc
