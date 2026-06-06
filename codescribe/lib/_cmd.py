import re
import os, json

from typing import List, Dict, Union, Optional, Any
from pathlib import Path
from alive_progress import alive_bar

from codescribe import lib

def _set_neural_model(model: Union[Path, str]) -> object:
    """Instantiate and return the appropriate LLM based on the model string."""
    if os.path.exists(model):
        return lib.TFModel(model)

    if model.lower().startswith("openai-"):
        return lib.OpenAIModel(model.lower().strip("openai")[1:])

    if model.lower().startswith("argo-"):
        return lib.ArgoModel(model.lower().strip("argo")[1:])

    if model.lower().startswith("anthropic-"):
        return lib.AnthropicModel(model[len("anthropic-"):])

    if model.lower().startswith("oaic-"):
        return lib.OpenAICompModel(model[len("oaic-"):])

    raise ValueError(
        f"Unknown model '{model}'. Use a recognized prefix: "
        "openai-, argo-, anthropic-, oaic-, or a local path."
    )


def prompt_translate(
    mapping: List[str],
    seed_prompt: Path,
    model: Union[Path, str] = None,
    save_prompts: bool = False,
) -> None:
    """Perform translation using prompts and the supplied model."""
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
    """Perform inspection on a list of files using a query prompt."""
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
    """Perform code generation based on the provided seed prompt."""
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
            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
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
    """Perform code updates based on the provided seed prompt and file list."""
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
            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
            with open(filename, "w") as f:
                f.write(content.strip() + "\n")
            print(f"Wrote {filename}")

        lib.create_archive_file(
            chat_template + [{"role": "assistant", "content": result}], neural_model
        )


def prompt_agent(
    task: str,
    model: Union[Path, str],
    system: str = "",
    tools: Optional[List] = None,
    max_iterations: int = 20,
    show_thinking: bool = False,
) -> str:
    """Run the agentic loop on *task* using the supplied model string.

    The model string uses the same prefix conventions as the other prompt_*
    functions (e.g. "anthropic-claude-sonnet-4-6", "openai-gpt-4o", etc.).
    The Agent drives the model through iterative tool calls until it emits a
    <final_answer> block and returns that text.

    Set show_thinking=True to print each iteration's reasoning and tool calls
    to stdout as the agent works.
    """
    neural_model = _set_neural_model(model)
    agent = lib.Agent(
        neural_model,
        tools=tools if tools is not None else lib.DEFAULT_TOOLS,
        max_iterations=max_iterations,
        show_thinking=show_thinking,
    )
    return agent.run(task, system=system)


def _ensure_within_workdir(path: Path, workdir: Path) -> Path:
    path = path.resolve()
    workdir = workdir.resolve()
    try:
        path.relative_to(workdir)
    except ValueError:
        raise ValueError(f"Path {path} is outside working directory {workdir}")
    return path


def _loop_paths(workdir: Path) -> Dict[str, Path]:
    loop_dir = workdir / ".codescribe" / "loop"
    return {
        "dir": loop_dir,
        "status": loop_dir / "status.json",
        "execution_report": loop_dir / "execution_report.md",
        "repair_report": loop_dir / "repair_report.md",
    }


def _write_loop_status(path: Path, payload: Dict[str, Any]) -> None:
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)


def prompt_loop(
    spec_file: Union[Path, str],
    validation_file: Union[Path, str],
    model: Union[Path, str],
    max_rounds: int = 5,
    agent_iterations: int = 12,
    show_thinking: bool = False,
    workdir: Optional[Union[Path, str]] = None,
) -> str:
    """
    Run a fresh-context execution/repair loop using two separate agents.

    Each round creates a new execution agent session and, if needed, a new repair
    agent session. No chat history is preserved across rounds; persistent state is
    inferred only from files in the working directory.
    """
    workdir_path = Path(workdir).resolve() if workdir else Path.cwd().resolve()
    spec_path = _ensure_within_workdir(Path(spec_file), workdir_path)
    validation_path = _ensure_within_workdir(Path(validation_file), workdir_path)

    neural_model = _set_neural_model(model)
    tools = lib.make_bounded_tools(workdir_path)
    paths = _loop_paths(workdir_path)
    os.makedirs(paths["dir"], exist_ok=True)

    spec_rel = spec_path.relative_to(workdir_path)
    validation_rel = validation_path.relative_to(workdir_path)
    status_rel = paths["status"].relative_to(workdir_path)
    execution_report_rel = paths["execution_report"].relative_to(workdir_path)
    repair_report_rel = paths["repair_report"].relative_to(workdir_path)

    execution_system = (
        "You are the execution and validation agent.\n"
        "Your job is to assess whether the current workspace satisfies the "
        "specification and validation procedure.\n"
        "You must not modify product/source files. You may only inspect files and run "
        "validation commands. You may write only the execution status/report files.\n"
        "Never read from, write to, or rely on any path above the working directory.\n"
        "Treat every session as fresh. Infer project state only from files and command output.\n"
    )

    repair_system = (
        "You are the repair agent.\n"
        "Your job is to modify the workspace so it satisfies the specification and passes "
        "the validation procedure.\n"
        "Use the specification, validation file, and latest execution report to guide fixes.\n"
        "Never read from, write to, or rely on any path above the working directory.\n"
        "Treat every session as fresh. Infer project state only from files and command output.\n"
        "Do not assume prior conversation context.\n"
    )

    for round_idx in range(1, max_rounds + 1):
        _write_loop_status(
            paths["status"],
            {
                "round": round_idx,
                "state": "execution",
                "passed": False,
            },
        )

        if show_thinking:
            print(f"\n▶  round {round_idx}  [execution]")

        execution_agent = lib.Agent(
            neural_model,
            tools=tools,
            max_iterations=agent_iterations,
            show_thinking=show_thinking,
        )

        execution_task = f"""
Working directory: {workdir_path}

Specification file: {spec_rel}
Validation file: {validation_rel}

Run the validation procedure for the current workspace.

Rules:
- You may inspect files and run shell commands needed for validation.
- Do not modify project source/product files.
- You may write only these files:
  - {execution_report_rel}
  - {status_rel}
- Write a concise human-readable validation report to {execution_report_rel}.
- Write JSON to {status_rel} with this schema:
  {{"round": {round_idx}, "state": "execution_complete", "passed": <true|false>, "summary": "<short summary>"}}
- If validation passes, set "passed" to true.
- If validation fails, set "passed" to false and include the most important failures in the summary.
- Finish with a <final_answer> that states PASS or FAIL.
""".strip()

        execution_result = execution_agent.run(execution_task, system=execution_system)

        with open(paths["status"], "r") as fh:
            status = json.load(fh)

        if status.get("passed") is True:
            if show_thinking:
                print(f"  ✓  pass\n")
            return f"✓  passed after {round_idx} round(s)  —  report: {paths['execution_report']}"

        if show_thinking:
            summary = status.get("summary", "")
            detail = f"  {summary[:65]}" if summary else ""
            print(f"  ✗  fail{detail}\n")

        _write_loop_status(
            paths["status"],
            {
                "round": round_idx,
                "state": "repair",
                "passed": False,
            },
        )

        if show_thinking:
            print(f"▶  round {round_idx}  [repair]")

        repair_agent = lib.Agent(
            neural_model,
            tools=tools,
            max_iterations=agent_iterations,
            show_thinking=show_thinking,
        )

        repair_task = f"""
Working directory: {workdir_path}

Specification file: {spec_rel}
Validation file: {validation_rel}
Latest execution report: {execution_report_rel}
Status file: {status_rel}

Repair the workspace so it satisfies the specification and passes validation.

Rules:
- You may read and modify files only within the working directory.
- Use the spec file, validation file, and execution report as the source of truth.
- Write a concise human-readable repair summary to {repair_report_rel}.
- Do not rely on any previous chat context; infer everything from files.
- Finish with a <final_answer> that summarizes what you changed.
""".strip()

        repair_result = repair_agent.run(repair_task, system=repair_system)

        if show_thinking:
            print(f"  ↩  repair complete\n")

        _write_loop_status(
            paths["status"],
            {
                "round": round_idx,
                "state": "repair_complete",
                "passed": False,
                "summary": repair_result,
            },
        )

    return f"✗  stopped after {max_rounds} round(s) without success  —  report: {paths['execution_report']}"
