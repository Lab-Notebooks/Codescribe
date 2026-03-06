# Prompt engineering for building diffusion stencils for constant and variable coefficient equations

# Import libraries
import re
import os, sys, importlib, json, requests

from typing import List, Dict, Union
from pathlib import Path
from alive_progress import alive_bar

from codescribe import lib


class OpenAICompModel:
    def __init__(self, model: str) -> None:
        openai = importlib.import_module("openai")

        self.baseurl = os.getenv("OPENAI_COMP_BASEURL")
        if not self.baseurl:
            raise ValueError("OPENAI_COMP_BASEURL environment variable is not set")

        self.provider = os.getenv("OPENAI_COMP_PROVIDER")
        if not self.provider:
            raise ValueError("OPENAI_COMP_PROVIDER environment variable is not set")

        if model.lower() == "env":
            self.model = os.getenv("OPENAI_COMP_MODEL")
        else:
            self.model = model

        if os.getenv("OPENAI_COMP_APIKEY"):
            self.apikey = os.getenv("OPENAI_COMP_APIKEY")

        elif "alcf" in self.provider:
            self.apikey = os.getenv("ALCF_INFERENCE_APIKEY")
            if not self.apikey:
                raise ValueError(
                    "ALCF_INFERENCE_APIKEY environment variable is not set"
                )
        else:
            self.apikey = "null"

        self.pipeline = openai.OpenAI(api_key=self.apikey, base_url=self.baseurl)
        self.outputs = 1
        self.max_tokens = 4096

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        response = self.pipeline.chat.completions.create(
            model=self.model,
            messages=chat_template,
            max_tokens=self.max_tokens,
            n=self.outputs,
        )

        return response.choices[0].message.content


class OpenAIModel:
    def __init__(self, model: str) -> None:
        openai = importlib.import_module("openai")
        self.pipeline = openai.OpenAI()
        self.outputs = 1
        self.max_tokens = 4096
        self.model = model

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        # We use the Chat Completion endpoint for chat-like inputs
        response = self.pipeline.chat.completions.create(
            # Model used here is ChatGPT
            # You can use all these models for this endpoint:
            # gpt-4, gpt-4-0314, gpt-4-32k, gpt-4-32k-0314,
            # gpt-3.5-turbo, gpt-3.5-turbo-0301, gpt-4o
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

    def chat(self, chat_template: List[Dict[str, str]]) -> str:

        if chat_template[0]["role"] == "system":
            system_prompt = chat_template[0]["content"]
            chat_template.pop(0)
        else:
            system_prompt = "You are a large language model named Argo."

        # Combine all role/content pairs into a single text block
        prompt_text = "\n\n".join(
            f"{item['role'].capitalize()}: {item['content'].strip()}"
            for item in chat_template
        )

        # Data to be sent as a POST in JSON format
        data = {
            "user": self.user,
            "model": self.model,
            "system": system_prompt,
            "prompt": [prompt_text],
            "stop": [],
            "temperature": 0.1,
            #"top_p": 0.9,
        }

        response = requests.post(
            self.api_endpoint,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        )

        return response.json()["response"]

    def __repr__(self) -> str:
        return f"ArgoModel(model='{self.model}', api_endpoint='***', user='***')"


class KimiModel:
    """
    Client for a locally hosted OpenAI-compatible Chat Completions API.

    Expects the API key in the environment variable: KIMI_API_KEY
    Expects the API endpoint in the environment variable: KIMI_API_ENDPOINT

    Default model:
      moonshotai/Kimi-K2-Instruct
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("KIMI_API_KEY")
        if not self.api_key:
            raise ValueError("KIMI_API_KEY environment variable is not set")

        self.endpoint = os.getenv("KIMI_API_ENDPOINT")
        if not self.endpoint:
            raise ValueError("KIMI_API_ENDPOINT environment variable is not set")

        self.model = "moonshotai/Kimi-K2-Instruct"
        self.outputs = 1
        self.max_tokens = 4096
        self.timeout = 120

        self._session = requests.Session()
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        """
        Send messages to the chat completion endpoint.

        Parameters
        ----------
        chat_template : list[dict]
            OpenAI-style messages, e.g.:
            [
              {"role": "system", "content": "You are helpful."},
              {"role": "user", "content": "Hello!"}
            ]

        Returns
        -------
        str
            The assistant's reply (first choice).
        """
        payload = {
            "model": self.model,
            "messages": chat_template,
            "max_tokens": self.max_tokens,
            "n": self.outputs,
        }

        resp = self._session.post(
            self.endpoint, headers=self._headers, json=payload, timeout=self.timeout
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}") from e

        data = resp.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected response format: {data}") from e

    def __repr__(self) -> str:
        return f"KimiModel(model='{self.model}', endpoint='***', outputs={self.outputs}, max_tokens={self.max_tokens})"


class QwenModel:
    """
    Client for a locally hosted OpenAI-compatible Chat Completions API.

    Expects the API key in the environment variable: KIMI_API_KEY
    Default endpoint:
      http://llm.ai.r-ccs.riken.jp:11434/kimi/v1/chat/completions
    Default model:
      moonshotai/Kimi-K2-Instruct
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("KIMI_API_KEY")
        if not self.api_key:
            raise ValueError("KIMI_API_KEY environment variable is not set")

        self.endpoint = os.getenv("KIMI_API_ENDPOINT")
        if not self.endpoint:
            raise ValueError("KIMI_API_ENDPOINT environment variable is not set")

        self.model = "qwen3-coder:30b"
        self.outputs = 1
        self.max_tokens = 4096
        self.timeout = 120

        self._session = requests.Session()
        self._headers = {
            "Content-Type": "application/json",
        }

    def chat(self, chat_template: List[Dict[str, str]]) -> str:
        """
        Send messages to the chat completion endpoint.

        Parameters
        ----------
        chat_template : list[dict]
            OpenAI-style messages, e.g.:
            [
              {"role": "system", "content": "You are helpful."},
              {"role": "user", "content": "Hello!"}
            ]

        Returns
        -------
        str
            The assistant's reply (first choice).
        """
        payload = {
            "model": self.model,
            "messages": chat_template,
            "max_tokens": self.max_tokens,
            "n": self.outputs,
        }

        resp = self._session.post(
            self.endpoint, headers=self._headers, json=payload, timeout=self.timeout
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}") from e

        data = resp.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected response format: {data}") from e

    def __repr__(self) -> str:
        return f"QwenModel(model='{self.model}', endpoint='***', outputs={self.outputs}, max_tokens={self.max_tokens})"


class TFModel:
    def __init__(self, checkpoint_dir: Path) -> None:
        transformers = importlib.import_module("transformers")
        torch = importlib.import_module("torch")

        self.tokenizer = transformers.AutoTokenizer.from_pretrained(checkpoint_dir)
        self.config = transformers.AutoConfig.from_pretrained(checkpoint_dir)
        self.pipeline = transformers.pipeline(
            "text-generation",
            model=checkpoint_dir,
            # torch_dtype=torch.float16,
            device=-1,
        )

        self.max_new_tokens = 4096
        self.batch_size = 8
        self.max_length = None

    def chat(self, chat_template: List[Dict[str, str]]) -> str:

        chat_template = _merge_system_with_user(chat_template)

        results = self.pipeline(
            chat_template,
            max_new_tokens=self.max_new_tokens,
            max_length=self.max_length,
            batch_size=self.batch_size,
            # temperature=temperature,
            # top_p=top_p,
            # do_sample=True,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=50256,
        )

        return results[0]["generated_text"][-1]["content"]

    def __repr__(self) -> str:
        return f"TFModel(model={self.config.model_type}, max_new_tokens={self.max_new_tokens}, batch_size={self.batch_size}, max_length={self.max_length})"


def _merge_system_with_user(
    chat_template: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """
    Remove the system role and prepend its contents to the first
    user role.
    """
    if chat_template and chat_template[0]["role"] == "system":
        system_content = chat_template[0]["content"]
        # Find the first user entry
        for msg in chat_template:
            if msg["role"] == "user":
                msg["content"] = system_content + "\n\n" + msg["content"]
                break
        # Remove the system entry
        chat_template = [msg for msg in chat_template if msg["role"] != "system"]

    return chat_template


def _set_neural_model(model: Union[Path, str]) -> object:
    """
    Set the neural model based on options.
    """
    if os.path.exists(model):
        neural_model = TFModel(model)

    elif model.lower().startswith("oaic-"):
        neural_model = OpenAICompModel(model.lower().strip("oaic")[1:])

    elif model.lower().startswith("openai-"):
        neural_model = OpenAIModel(model.lower().strip("openai")[1:])

    elif model.lower().startswith("argo-"):
        neural_model = ArgoModel(model.lower().strip("argo")[1:])

    elif model.lower() == "kimi":
        neural_model = KimiModel()

    elif model.lower() == "qwen":
        neural_model = QwenModel()

    else:
        raise ValueError(f"{model} is not available")

    return neural_model


def prompt_translate(
    mapping: List[str],
    seed_prompt: Path,
    model: Union[Path, str] = None,
    save_prompts: bool = False,
) -> None:
    """
    Perform translation using prompts and the supplied model.
    """
    neural_model = None

    if model:
        print("Starting neural conversion process")
        neural_model = _set_neural_model(model)

    if save_prompts:
        print("Saving custom prompts per file")

    chat_template = lib.load_chat_template(seed_prompt)

    with alive_bar(len(mapping[0]), bar="blocks") as bar:

        for fsource, csource, finterface, cdraft, promptfile, cheader in zip(
            mapping[0], mapping[1], mapping[2], mapping[3], mapping[4], mapping[5]
        ):

            bar.text(fsource)
            bar()

            if not os.path.isfile(csource) or save_prompts:
                cached_prompt = chat_template[-1]["content"]

                with open(fsource, "r") as sfile:
                    is_comment = False
                    source_code = []

                    for line in sfile.readlines():
                        is_comment = False

                        if line.strip().lower().startswith(("c", "!!", "!")) and (
                            not line.strip().lower().startswith(("complex"))
                        ):
                            is_comment = True

                        if not is_comment:
                            source_code.append(line)

                    if source_code:
                        chat_template[-1]["content"] += (
                            "\n" + "<source>\n" + "".join(source_code) + "</source>"
                        )

                if os.path.isfile(cdraft):

                    draft_code = []
                    with open(cdraft) as dfile:
                        for line in dfile.readlines():
                            draft_code.append(line)

                        if draft_code:
                            chat_template[-1]["content"] += (
                                "\n\n" + "<draft>\n" + "".join(draft_code) + "</draft>"
                            )

                if save_prompts:
                    with open(promptfile, "w") as pdest:
                        json.dump(chat_template, pdest, indent=4)
                    print(f"Generated prompt file for LLM consumption {promptfile}")

                if neural_model:
                    result = neural_model.chat(chat_template)

                    with open(csource, "w") as cdest, open(
                        finterface, "w"
                    ) as fdest, open(cheader, "w") as chead:

                        cheader = re.search(
                            r"<cheader>(.*?)</cheader>", result, re.DOTALL
                        )
                        csource = re.search(
                            r"<csource>(.*?)</csource>", result, re.DOTALL
                        )
                        fsource = re.search(
                            r"<fsource>(.*?)</fsource>", result, re.DOTALL
                        )

                        if csource:
                            cdest.write(csource.group(1))
                        else:
                            cdest.write(result)

                        if cheader:
                            chead.write(cheader.group(1))
                        else:
                            chead.write(result)

                        if fsource:
                            fdest.write(fsource.group(1))

                lib.create_archive_file(
                    chat_template + [{"role": "assistant", "content": result}],
                    neural_model,
                )

                chat_template[-1]["content"] = cached_prompt

            else:
                continue


def prompt_inspect(
    filelist: List[Path],
    query_prompt: str,
    file_index: Dict[str, str] = {},
    model: Union[Path, str] = None,
    save_prompts: bool = False,
) -> None:
    """
    Perform inspection on a list of files using a query prompt.
    """
    neural_model = None

    if model:
        print("Performing neural inspection")
        neural_model = _set_neural_model(model)

    if save_prompts:
        print("Saving prompts to scribe.json")

    chat_template = [{"role": "system", "content": ""}]

    chat_template[-1]["content"] += (
        "You are a coding assistant.\n"
        + "The user will provide source code from a set of files that\n"
        + "belong to a scientific computing codebase. Understand the\n"
        + "source code and answer a query that follows.\n"
        + "Source code for each file will be separated using\n"
        + "elements <filename> ... </filename>. Additional\n"
        + "information related to the project structure may also be\n"
        + "provided within <index> ... </index>. This information will\n"
        + "contain an index of subroutines, functions, and modules contained\n"
        + "in each file. Note that you will find subroutines and functions\n"
        + "repeated along nodes in the directory tree. This may be due to a directory-based\n"
        + "inheritance design implemented by the project. If the index element is not\n"
        + "present, then you may ignore it. The query prompt will be provided at the end\n"
        + "using elements <query> ... </query>.\n\n"
    )

    chat_template.append({"role": "user", "content": ""})

    filtered_file_index = {}
    for fsource in filelist:

        if file_index:
            filtered_file_index.update(lib.filter_file_indexes(fsource, file_index))

        with open(fsource, "r") as sfile:
            source_code = []

            for line in sfile.readlines():
                source_code.append(line)

        if source_code:
            chat_template[-1]["content"] += (
                "\n" + f"<{fsource}>\n" + "".join(source_code) + f"</{fsource}>\n"
            )

    if filtered_file_index:
        chat_template[-1]["content"] += "<index>\n"
        for construct, file_path in filtered_file_index.items():
            chat_template[-1]["content"] += f"{construct}: {file_path}\n"
        chat_template[-1]["content"] += "</index>\n\n"

    chat_template[-1]["content"] += "\n" + f"<query>\n" + query_prompt + f"\n</query>\n"

    if save_prompts:
        with open("scribe.json", "w") as pdest:
            json.dump(chat_template, pdest, indent=4)

    if neural_model:
        result = neural_model.chat(chat_template)
        print(result)


def prompt_generate(
    seed_prompt: Union[Path, str],
    model: Union[Path, str] = None,
    save_prompts: bool = False,
    reference_existing: List[Path] = [],
) -> None:
    """
    Perform code generation based on the provided seed prompt.
    """
    neural_model = None

    if model:
        print("Performing neural generation")
        neural_model = _set_neural_model(model)

    if save_prompts:
        print("Saving prompts to scribe.json")

    system_template = [{"role": "system", "content": ""}]
    system_template[-1]["content"] += (
        "You are a code generation and editing assistant.\n"
        + "When the user asks for code that spans multiple files,\n"
        + "output each file enclosed within\n"
        + "XML-style tags using the format:\n"
        + "\n"
        + "<filename1>\n"
        + "... file contents ...\n"
        + "</filename1>\n"
        + "\n"
        + "<filename2>\n"
        + "... file contents ...\n"
        + "</filename2>\n"
        + "\n"
        + "Do not add any explanations or commentary outside of these tags.\n"
        + "Note that some of these files may be requested to be treated as read-only.\n"
        + "Do not edit or generate files that are requested as read-only."
    )

    if os.path.exists(seed_prompt):
        chat_template = system_template + lib.load_chat_template(seed_prompt)
    elif isinstance(seed_prompt, str):
        chat_template = system_template + [{"role": "user", "content": seed_prompt}]
    else:
        raise ValueError(f"Cannot handle seed_prompt")

    if reference_existing:
        chat_template[-1]["content"] += (
            "\n\nUse the content of the following files as a reference to \n"
            + "update the files above. Do not edit the files below; treat them as read-only.\n\n"
        )

        for filename in reference_existing:
            with open(filename, "r") as sfile:
                source_code = []

                for line in sfile.readlines():
                    source_code.append(line)

            if source_code:
                chat_template[-1]["content"] += (
                    "\n" + f"<{filename}>\n" + "".join(source_code) + f"</{filename}>\n"
                )

    if save_prompts:
        with open("scribe.json", "w") as pdest:
            json.dump(chat_template, pdest, indent=4)

    if neural_model:
        result = neural_model.chat(chat_template)

        pattern = re.compile(r"<([^>]+)>\s*(.*?)\s*</\1>", re.DOTALL)

        for match in pattern.finditer(result):
            filename, content = match.groups()
            # Ensure directory exists if filename has subpaths
            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
            # Write to file
            with open(filename, "w") as f:
                f.write(content.strip() + "\n")
            print(f"Wrote {filename}")

        lib.create_archive_file(
            chat_template + [{"role": "assistant", "content": result}], neural_model
        )


def prompt_update(
    filelist: List[Path],
    seed_prompt: Path,
    query_prompt: str,
    model: Union[Path, str] = None,
    reference_existing: List[Path] = [],
):
    """
    Perform code updates based on the provided seed prompt and file list.
    """
    neural_model = None

    print("Performing neural update")
    neural_model = _set_neural_model(model)

    system_template = [{"role": "system", "content": ""}]
    system_template[-1]["content"] += (
        "You are a code generation and editing assistant.\n"
        + "When the user asks for code that spans multiple files,\n"
        + "output each file enclosed within\n"
        + "XML-style tags using the format:\n"
        + "\n"
        + "<filename1>\n"
        + "... file contents ...\n"
        + "</filename1>\n"
        + "\n"
        + "<filename2>\n"
        + "... file contents ...\n"
        + "</filename2>\n"
        + "\n"
        + "Do not add any explanations or commentary outside of these tags.\n"
        + "Note that some of these files may be requested to be treated as \n"
        + "read-only or may not be appended.\n"
        + "Do not edit files if they are not appended or requested as read-only."
    )

    if seed_prompt:
        chat_template = system_template + lib.load_chat_template(seed_prompt)
    else:
        chat_template = system_template + [{"role": "user", "content": ""}]

    if query_prompt:
        chat_template[-1]["content"] += query_prompt

    if set(filelist) & set(reference_existing):
        raise ValueError("Reference and target files should be mutually exclusive")

    if filelist:
        chat_template[-1]["content"] += (
            "\n\nUpdate the content of the following files based on\n"
            + "the instructions. Enclose the output of each file in their\n"
            + "respective XML elements. Only update the following files.\n\n"
        )

        for filename in filelist:
            with open(filename, "r") as sfile:
                source_code = []

                for line in sfile.readlines():
                    source_code.append(line)

            if source_code:
                chat_template[-1]["content"] += (
                    "\n" + f"<{filename}>\n" + "".join(source_code) + f"</{filename}>\n"
                )

    if reference_existing:
        chat_template[-1]["content"] += (
            "Use the content of the following files as a reference to \n"
            + "update the files above. Do not edit the files below; treat them as read-only.\n\n"
        )

        for filename in reference_existing:
            with open(filename, "r") as sfile:
                source_code = []

                for line in sfile.readlines():
                    source_code.append(line)

            if source_code:
                chat_template[-1]["content"] += (
                    "\n" + f"<{filename}>\n" + "".join(source_code) + f"</{filename}>\n"
                )

    if neural_model:
        result = neural_model.chat(chat_template)

        pattern = re.compile(r"<([^>]+)>\s*(.*?)\s*</\1>", re.DOTALL)

        for match in pattern.finditer(result):
            filename, content = match.groups()
            # Ensure directory exists if filename has subpaths
            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
            # Write to file
            with open(filename, "w") as f:
                f.write(content.strip() + "\n")
            print(f"Wrote {filename}")

        lib.create_archive_file(
            chat_template + [{"role": "assistant", "content": result}], neural_model
        )
