from __future__ import annotations

import os, importlib, json, requests

from typing import Any, List, Dict, Union
from pathlib import Path


class _OpenAIBaseModel:
    outputs = 1
    # Provider "max_tokens" (OpenAI Responses/ChatCompletions style) is the maximum
    # number of tokens the model may generate for the reply (i.e., output tokens).
    # Default bumped to allow more verbose reasoning / planning.
    max_tokens = int(os.getenv("CODESCRIBE_MAX_TOKENS", "24576"))

    @property
    def supports_native_tools(self) -> bool:
        return True

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        response = self.pipeline.chat.completions.create(
            model=self.model,
            messages=chat_template,
            max_tokens=self.max_tokens,
            n=self.outputs,
        )
        self.last_usage = _normalize_openai_usage(getattr(response, "usage", None))
        return response.choices[0].message.content

    def chat_with_tools(
        self, chat_template: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        response = self.pipeline.chat.completions.create(
            model=self.model,
            messages=chat_template,
            tools=tools,
            max_tokens=self.max_tokens,
            n=self.outputs,
        )
        self.last_usage = _normalize_openai_usage(getattr(response, "usage", None))
        return _normalize_openai_tool_response(
            response.choices[0].message, self.last_usage
        )

    def format_tool_result_messages(
        self, tool_calls: List[Dict[str, Any]], outputs: List[str]
    ) -> List[Dict[str, Any]]:
        assistant_tool_calls = []
        for call in tool_calls:
            assistant_tool_calls.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                }
            )

        messages: List[Dict[str, Any]] = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": assistant_tool_calls,
            }
        ]
        for call, output in zip(tool_calls, outputs):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                }
            )
        return messages


class OpenAICompModel(_OpenAIBaseModel):
    def __init__(self, model: str) -> None:
        openai = importlib.import_module("openai")

        self.baseurl = os.getenv("OPENAI_COMP_BASEURL")
        if not self.baseurl:
            raise ValueError("OPENAI_COMP_BASEURL environment variable is not set")

        self.provider = os.getenv("OPENAI_COMP_PROVIDER")
        if not self.provider:
            raise ValueError("OPENAI_COMP_PROVIDER environment variable is not set")

        self.model = model

        self.apikey = os.getenv("OPENAI_COMP_APIKEY")
        if not self.apikey:
            raise ValueError("OPENAI_COMP_APIKEY environment variable is not set")

        self.pipeline = openai.OpenAI(api_key=self.apikey, base_url=self.baseurl)
        self.last_usage = None

    def __repr__(self) -> str:
        return f"OpenAICompModel(model='{self.model}')"


class OpenAIModel(_OpenAIBaseModel):
    def __init__(self, model: str) -> None:
        openai = importlib.import_module("openai")

        self.apikey = os.getenv("OPENAI_API_KEY")
        if not self.apikey:
            raise ValueError("OPENAI_API_KEY environment variable is not set")

        self.pipeline = openai.OpenAI(api_key=self.apikey)
        self.model = model
        self.last_usage = None

    def __repr__(self) -> str:
        return f"OpenAIModel(model='{self.model}', outputs={self.outputs}, max_tokens={self.max_tokens})"


class ArgoModel:
    def __init__(self, model: str) -> None:

        self.api_endpoint = os.getenv("ARGO_API_ENDPOINT")
        if not self.api_endpoint:
            raise ValueError("ARGO_API_ENDPOINT environment variable is not set")

        self.user = os.getenv("ARGO_USER")
        if not self.user:
            raise ValueError("ARGO_USER environment variable is not set")

        self.model = model
        self.last_usage = None

    @property
    def supports_native_tools(self) -> bool:
        # Tool calling is implemented via prompt-mediated strict JSON, not provider-native tools.
        return True

    def _post(self, system_prompt: str, prompt_text: str) -> str:
        data = {
            "user": self.user,
            "model": self.model,
            "system": system_prompt,
            "prompt": [prompt_text],
            "stop": [],
            "temperature": 0.1,
        }

        response = requests.post(
            self.api_endpoint,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        )
        return response.json()["response"]

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        chat_template = list(chat_template)  # don't mutate caller's list

        if chat_template and chat_template[0]["role"] == "system":
            system_prompt = chat_template[0]["content"]
            chat_template.pop(0)
        else:
            system_prompt = "You are a large language model named Argo."

        prompt_text = "\n\n".join(
            f"{item['role'].capitalize()}: {item['content'].strip()}"
            for item in chat_template
        )

        return self._post(system_prompt, prompt_text)

    def chat_with_tools(
        self, chat_template: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        # Provider doesn't support structured tools; enforce strict JSON output.
        chat_template = list(chat_template)

        if chat_template and chat_template[0].get("role") == "system":
            system_prompt = chat_template[0].get("content") or ""
            chat_template.pop(0)
        else:
            system_prompt = ""

        tool_system = (
            _STRICT_TOOL_JSON_SYSTEM + "\n\n" + _tools_to_strict_json_spec(tools)
        )
        system_prompt = (system_prompt + "\n\n" + tool_system).strip()

        prompt_text = "\n\n".join(
            f"{item['role'].capitalize()}: {(item.get('content') or '').strip()}"
            for item in chat_template
        )

        raw = self._post(system_prompt, prompt_text)
        parsed = _parse_strict_tool_json(raw)
        self.last_usage = None
        return {
            "text": parsed.get("text", ""),
            "tool_calls": parsed.get("tool_calls", []),
            "usage": None,
        }

    def format_tool_result_messages(
        self, tool_calls: List[Dict[str, Any]], outputs: List[str]
    ) -> List[Dict[str, Any]]:
        # OpenAI-style tool result messages.
        assistant_tool_calls = []
        for call in tool_calls:
            assistant_tool_calls.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                }
            )

        messages: List[Dict[str, Any]] = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": assistant_tool_calls,
            }
        ]
        for call, output in zip(tool_calls, outputs):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                }
            )
        return messages

    def __repr__(self) -> str:
        return f"ArgoModel(model='{self.model}', api_endpoint='***', user='***')"


class AnthropicModel:
    def __init__(self, model: str) -> None:
        anthropic = importlib.import_module("anthropic")

        self.apikey = os.getenv("ANTHROPIC_API_KEY")
        if not self.apikey:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

        self.base_url = os.getenv("ANTHROPIC_BASE_URL")
        client_kwargs = {"api_key": self.apikey}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = anthropic.Anthropic(**client_kwargs)
        self.model = model
        # Anthropic "max_tokens" is the maximum output tokens to generate.
        self.max_tokens = int(os.getenv("CODESCRIBE_MAX_TOKENS", "24576"))
        self.last_usage = None

    @property
    def supports_native_tools(self) -> bool:
        return True

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        system = None
        messages = []
        for msg in chat_template:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                messages.append({"role": msg["role"], "content": msg["content"]})

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        # Newer anthropic-sdk-python versions require streaming for long requests
        # (server-side enforcement for operations that may exceed ~10 minutes).
        # We prefer streaming here and reconstruct the final text.
        try:
            stream = self.client.messages.stream(**kwargs)
        except Exception:
            # Fallback to non-streaming if the installed SDK/provider permits it.
            response = self.client.messages.create(**kwargs)
            self.last_usage = _normalize_anthropic_usage(getattr(response, "usage", None))
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        text_parts: List[str] = []
        final_message = None
        with stream as s:
            for event in s:
                # Collect text deltas.
                if getattr(event, "type", None) == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) == "text_delta":
                        text_parts.append(getattr(delta, "text", "") or "")
                # Keep a handle to the final message so we can extract usage.
                if getattr(event, "type", None) == "message_stop":
                    final_message = getattr(event, "message", None)

        self.last_usage = _normalize_anthropic_usage(
            getattr(final_message, "usage", None) if final_message is not None else None
        )
        return "".join(text_parts)

    def chat_with_tools(
        self, chat_template: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        system = None
        messages = []
        for msg in chat_template:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                messages.append(msg)

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
            "tools": [_openai_tool_to_anthropic_tool(tool) for tool in tools],
        }
        if system:
            kwargs["system"] = system

        # Prefer streaming for long requests; accumulate events and normalize into
        # the same {text, tool_calls, usage} shape as non-streaming.
        try:
            stream = self.client.messages.stream(**kwargs)
        except Exception:
            response = self.client.messages.create(**kwargs)
            usage = _normalize_anthropic_usage(getattr(response, "usage", None))
            self.last_usage = usage
            return _normalize_anthropic_tool_response(response, usage)

        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        final_message = None

        with stream as s:
            for event in s:
                et = getattr(event, "type", None)

                if et == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) == "text_delta":
                        text_parts.append(getattr(delta, "text", "") or "")
                    elif getattr(delta, "type", None) == "input_json_delta":
                        # Tool use input JSON arrives as deltas; the SDK also emits a
                        # full "tool_use" block in message_stop.final_message. We
                        # ignore these deltas and rely on the final message parse.
                        pass

                if et == "message_stop":
                    final_message = getattr(event, "message", None)

        usage = _normalize_anthropic_usage(
            getattr(final_message, "usage", None) if final_message is not None else None
        )
        self.last_usage = usage

        # Normalize tool calls from the final message content.
        response = final_message
        if response is None:
            return {"text": "".join(text_parts), "tool_calls": [], "usage": usage}

        normalized = _normalize_anthropic_tool_response(response, usage)
        # If the normalizer didn't include text (because it focuses on tool calls),
        # use the streamed text as a fallback.
        if not normalized.get("text"):
            normalized["text"] = "".join(text_parts)
        return normalized

    def format_tool_result_messages(
        self, tool_calls: List[Dict[str, Any]], outputs: List[str]
    ) -> List[Dict[str, Any]]:
        assistant_content = []
        for call in tool_calls:
            assistant_content.append(
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call["arguments"],
                }
            )

        user_content = []
        for call, output in zip(tool_calls, outputs):
            user_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": output,
                }
            )

        return [
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": user_content},
        ]

    def __repr__(self) -> str:
        return f"AnthropicModel(model='{self.model}')"


class TFModel:
    def __init__(self, checkpoint_dir: Path) -> None:
        transformers = importlib.import_module("transformers")
        torch = importlib.import_module("torch")

        self.tokenizer = transformers.AutoTokenizer.from_pretrained(checkpoint_dir)
        self.config = transformers.AutoConfig.from_pretrained(checkpoint_dir)
        self.pipeline = transformers.pipeline(
            "text-generation",
            model=checkpoint_dir,
            device=-1,
        )

        self.max_new_tokens = 4096
        self.batch_size = 8
        self.max_length = None
        self.last_usage = None

    @property
    def supports_native_tools(self) -> bool:
        # Tool calling is implemented via prompt-mediated strict JSON.
        return True

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        chat_template = _merge_system_with_user(chat_template)

        results = self.pipeline(
            chat_template,
            max_new_tokens=self.max_new_tokens,
            max_length=self.max_length,
            batch_size=self.batch_size,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=50256,
        )

        return results[0]["generated_text"][-1]["content"]

    def chat_with_tools(
        self, chat_template: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        # Local models don't have native tool calling; enforce strict JSON output.
        augmented = list(chat_template)
        tool_spec = (
            _STRICT_TOOL_JSON_SYSTEM + "\n\n" + _tools_to_strict_json_spec(tools)
        )

        if augmented and augmented[0].get("role") == "system":
            augmented[0] = dict(augmented[0])
            augmented[0]["content"] = (
                (augmented[0].get("content") or "") + "\n\n" + tool_spec
            ).strip()
        else:
            augmented.insert(0, {"role": "system", "content": tool_spec})

        prompt = _merge_system_with_user(
            [{"role": m["role"], "content": m.get("content") or ""} for m in augmented]
        )

        results = self.pipeline(
            prompt,
            max_new_tokens=self.max_new_tokens,
            max_length=self.max_length,
            batch_size=self.batch_size,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=50256,
        )

        raw = results[0]["generated_text"][-1]["content"]
        parsed = _parse_strict_tool_json(raw)
        self.last_usage = None
        return {
            "text": parsed.get("text", ""),
            "tool_calls": parsed.get("tool_calls", []),
            "usage": None,
        }

    def format_tool_result_messages(
        self, tool_calls: List[Dict[str, Any]], outputs: List[str]
    ) -> List[Dict[str, Any]]:
        # OpenAI-style tool result messages.
        assistant_tool_calls = []
        for call in tool_calls:
            assistant_tool_calls.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                }
            )

        messages: List[Dict[str, Any]] = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": assistant_tool_calls,
            }
        ]
        for call, output in zip(tool_calls, outputs):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                }
            )
        return messages

    def __repr__(self) -> str:
        return f"TFModel(model={self.config.model_type}, max_new_tokens={self.max_new_tokens}, batch_size={self.batch_size}, max_length={self.max_length})"


def _normalize_openai_tool_response(message: Any, usage: Any = None) -> Dict[str, Any]:
    text = message.content or ""
    tool_calls = []
    for call in getattr(message, "tool_calls", []) or []:
        raw_args = call.function.arguments or "{}"
        raw_args_str = raw_args if isinstance(raw_args, str) else str(raw_args)
        raw_args_err: str | None = None
        try:
            arguments = json.loads(raw_args_str)
        except Exception as exc:
            # Keep arguments empty so schema validation triggers a clear error,
            # but preserve raw args for agent self-correction.
            arguments = {}
            raw_args_err = f"{type(exc).__name__}: {exc}"

        item: Dict[str, Any] = {
            "id": call.id,
            "name": call.function.name,
            "arguments": arguments,
        }
        if raw_args_err is not None:
            item["_raw_arguments"] = raw_args_str
            item["_raw_arguments_error"] = raw_args_err

        tool_calls.append(item)

    return {
        "text": text,
        "tool_calls": tool_calls,
        "usage": _normalize_openai_usage(usage),
    }


def _normalize_openai_usage(usage: Any) -> Any:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage

    normalized = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
    ):
        value = getattr(usage, key, None)
        if value is not None:
            normalized[key] = value

    if not normalized and hasattr(usage, "model_dump"):
        return usage.model_dump()
    if not normalized and hasattr(usage, "dict"):
        return usage.dict()
    return normalized or None


def _openai_tool_to_anthropic_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    fn = tool["function"]
    return {
        "name": fn["name"],
        "description": fn.get("description", ""),
        "input_schema": fn["parameters"],
    }


def _normalize_anthropic_usage(usage: Any) -> Any:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage

    normalized = {}
    for src, dst in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("cache_creation_input_tokens", "cache_creation_input_tokens"),
        ("cache_read_input_tokens", "cache_read_input_tokens"),
    ):
        value = getattr(usage, src, None)
        if value is not None:
            normalized[dst] = value

    if not normalized and hasattr(usage, "model_dump"):
        return usage.model_dump()
    if not normalized and hasattr(usage, "dict"):
        return usage.dict()
    return normalized or None


def _normalize_anthropic_tool_response(
    response: Any, usage: Any = None
) -> Dict[str, Any]:
    texts = []
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "name": block.name,
                    "arguments": dict(block.input or {}),
                }
            )
    return {
        "text": "\n".join(t for t in texts if t).strip(),
        "tool_calls": tool_calls,
        "usage": usage,
    }


_STRICT_TOOL_JSON_SYSTEM = """\
You are a coding agent with access to tools.

When you want to use a tool, you MUST respond with exactly one JSON object and nothing else.
The JSON object MUST match this schema:
{
  \"text\": string,              # optional natural language to show to user (can be empty)
  \"tool_calls\": [
    {
      \"id\": string,
      \"name\": string,
      \"arguments\": object
    }
  ]
}

If you do not need tools, respond with exactly one JSON object of the same form with tool_calls=[] and put your final answer in text.
Do not wrap in markdown fences. Do not output any other keys.
"""


def _tools_to_strict_json_spec(tools: List[Dict[str, Any]]) -> str:
    # Tools are passed in OpenAI format. We embed only the essentials to reduce tokens.
    lines = ["AVAILABLE TOOLS (names + JSON schemas):"]
    for t in tools or []:
        fn = (t or {}).get("function") or {}
        name = fn.get("name")
        params = fn.get("parameters")
        desc = fn.get("description", "")
        if not name or params is None:
            continue
        lines.append(f"- {name}: {desc}".strip())
        lines.append(json.dumps(params, ensure_ascii=False))
    return "\n".join(lines).strip()


def _parse_strict_tool_json(raw: str) -> Dict[str, Any]:
    """Parse the strict tool-call JSON object.

    Some providers occasionally return multiple JSON objects concatenated
    (e.g. one per candidate). In that case we accept the *first* JSON object
    and ignore trailing data.
    """

    s = (raw or "").strip()
    try:
        obj = json.loads(s)
    except Exception:
        # Try to decode just the first JSON value (tolerate trailing data).
        try:
            decoder = json.JSONDecoder()
            obj, end = decoder.raw_decode(s)
            # If raw_decode succeeded but didn't consume all input, ignore the rest.
            _ = end
        except Exception as exc:
            # Strict mode: fail closed so the agent doesn't silently skip tool calls.
            raise ValueError(
                "Model did not return strict tool-call JSON. "
                "Expected a single JSON object with keys: text, tool_calls. "
                f"Raw output starts with: {s[:200]!r}"
            ) from exc

    if not isinstance(obj, dict):
        raise ValueError(
            "Model returned JSON but not an object. "
            f"Got: {type(obj).__name__}. Raw output starts with: {s[:200]!r}"
        )

    text = obj.get("text")
    if not isinstance(text, str):
        text = ""

    tool_calls_in = obj.get("tool_calls")
    tool_calls: List[Dict[str, Any]] = []
    if isinstance(tool_calls_in, list):
        for i, call in enumerate(tool_calls_in):
            if not isinstance(call, dict):
                continue
            cid = call.get("id")
            name = call.get("name")
            args = call.get("arguments")
            if not isinstance(cid, str) or not cid:
                cid = f"call_{i+1}"
            if not isinstance(name, str) or not name:
                continue
            if not isinstance(args, dict):
                args = {}
            tool_calls.append({"id": cid, "name": name, "arguments": args})

    return {"text": text, "tool_calls": tool_calls}


def _merge_system_with_user(
    chat_template: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Return a new chat template with system content prepended to the first user message.

    This function does not mutate the caller's message dicts.
    """

    if not chat_template:
        return []

    # Work on copies to avoid mutating caller-owned dicts.
    copied = [dict(m) for m in chat_template]

    if copied[0].get("role") != "system":
        return copied

    system_content = copied[0].get("content", "")
    out: List[Dict[str, str]] = []
    system_applied = False

    for msg in copied[1:]:
        if (not system_applied) and msg.get("role") == "user":
            msg["content"] = (
                system_content + "\n\n" + (msg.get("content") or "")
            ).rstrip()
            system_applied = True
        out.append(msg)

    # If there was a system message but no user message, just drop the system.
    return out


ALLOWED_MODEL_TYPES = (OpenAIModel, OpenAICompModel, AnthropicModel, ArgoModel, TFModel)
Model = Union[OpenAIModel, OpenAICompModel, AnthropicModel, ArgoModel, TFModel]


def set_neural_model(model: Union[Path, str]) -> Model:
    """Instantiate and return the appropriate LLM based on the model string."""
    model_str = str(model)
    if os.path.exists(model_str):
        return TFModel(Path(model_str))

    if model.lower().startswith("openai-"):
        return OpenAIModel(model.lower().strip("openai")[1:])

    if model.lower().startswith("argo-"):
        return ArgoModel(model.lower().strip("argo")[1:])

    if model.lower().startswith("anthropic-"):
        return AnthropicModel(model[len("anthropic-") :])

    if model.lower().startswith("oaic-"):
        return OpenAICompModel(model[len("oaic-") :])

    raise ValueError(
        f"Unknown model '{model}'. Use a recognized prefix: "
        "openai-, argo-, anthropic-, oaic-, or a local path."
    )
