import os, importlib, json, requests

from typing import List, Dict
from pathlib import Path


class OpenAICompModel:
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
        self.outputs = 1
        self.max_tokens = 16384

    @property
    def supports_native_tools(self) -> bool:
        return False

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        response = self.pipeline.chat.completions.create(
            model=self.model,
            messages=chat_template,
            max_tokens=self.max_tokens,
            n=self.outputs,
        )

        return response.choices[0].message.content

    def __repr__(self) -> str:
        return f"OpenAICompModel(model='{self.model}')"


class OpenAIModel:
    def __init__(self, model: str) -> None:
        openai = importlib.import_module("openai")
        self.pipeline = openai.OpenAI()
        self.outputs = 1
        self.max_tokens = 16384
        self.model = model

    @property
    def supports_native_tools(self) -> bool:
        return False

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        response = self.pipeline.chat.completions.create(
            model=self.model,
            messages=chat_template,
            max_tokens=self.max_tokens,
            n=self.outputs,
        )

        return response.choices[0].message.content

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

    @property
    def supports_native_tools(self) -> bool:
        return False

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        chat_template = list(chat_template)  # don't mutate caller's list

        if chat_template[0]["role"] == "system":
            system_prompt = chat_template[0]["content"]
            chat_template.pop(0)
        else:
            system_prompt = "You are a large language model named Argo."

        prompt_text = "\n\n".join(
            f"{item['role'].capitalize()}: {item['content'].strip()}"
            for item in chat_template
        )

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

    def __repr__(self) -> str:
        return f"ArgoModel(model='{self.model}', api_endpoint='***', user='***')"


class AnthropicModel:
    def __init__(self, model: str) -> None:
        anthropic = importlib.import_module("anthropic")

        self.apikey = os.getenv("ANTHROPIC_API_KEY")
        if not self.apikey:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

        self.client = anthropic.Anthropic(api_key=self.apikey)
        self.model = model
        self.max_tokens = 16384

    @property
    def supports_native_tools(self) -> bool:
        return False

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

        response = self.client.messages.create(**kwargs)

        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

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

    @property
    def supports_native_tools(self) -> bool:
        return False

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

    def __repr__(self) -> str:
        return f"TFModel(model={self.config.model_type}, max_new_tokens={self.max_new_tokens}, batch_size={self.batch_size}, max_length={self.max_length})"


def _merge_system_with_user(
    chat_template: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Prepend the system message content to the first user message."""
    if chat_template and chat_template[0]["role"] == "system":
        system_content = chat_template[0]["content"]
        for msg in chat_template:
            if msg["role"] == "user":
                msg["content"] = system_content + "\n\n" + msg["content"]
                break
        chat_template = [msg for msg in chat_template if msg["role"] != "system"]

    return chat_template
