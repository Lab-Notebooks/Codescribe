"""Command line interface for Jobrunner"""

# Standard libraries
import os
from pathlib import Path
from typing import Union, List

# Feature libraries
import click

from codescribe.cli import code_scribe
from codescribe import api
from codescribe import lib


@code_scribe.command(name="index")
@click.argument("root-dir", required=True, type=click.Path(exists=True))
def index(root_dir: Path) -> None:
    """
    \b
    Index Fortran files along a project directory tree
    \b

    \b
    This command walks along the directory directory tree and
    parses files to creating mapping for modules, subroutines,
    and functions
    \b
    """
    message: str = api.index(Path(os.path.abspath(root_dir)))
    click.echo(message)


@code_scribe.command(name="draft")
@click.argument("fortran-files", nargs=-1, required=True, type=click.Path(exists=True))
def draft(fortran_files: List[Path]) -> None:
    """
    \b
    Perform a draft conversion from Fortran to C++
    \b

    \b
    This command performs a line-by-line conversion to
    prepare a list of files for generative AI use
    \b
    """
    api.draft([Path(file) for file in fortran_files])


@code_scribe.command(name="translate")
@click.argument("fortran-files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--seed-prompt", "-p", required=True, help="TOML seed file for chat template"
)
@click.option(
    "--model",
    "-m",
    cls=lib.MutuallyExclusiveOption,
    help="Gen AI model name or path",
    mutually_exclusive=["save_prompts"],
)
@click.option(
    "--save-prompts",
    "-s",
    is_flag=True,
    cls=lib.MutuallyExclusiveOption,
    help="Save file specific prompts to json file",
    mutually_exclusive=["model"],
)
def translate(
    fortran_files: List[Path],
    seed_prompt: Path,
    model: Union[str, Path],
    save_prompts: bool,
) -> None:
    """
    \b
    Perform AI based code conversion of Fortran files
    \b

    \b
    This command applies generative AI to convert code from
    Fortran to C++, and create a corresponding Fortran/C
    interface
    \b
    """
    if (not model) and (not save_prompts):
        model = os.getenv("CODESCRIBE_MODEL")
        if not model:
            raise click.UsageError(
                "Please provide either the '--model/-m' or '--save-prompts/-p' option"
            )

    api.translate(
        [Path(file) for file in fortran_files],
        Path(seed_prompt),
        model,
        save_prompts,
    )


@code_scribe.command(name="generate")
@click.argument("seed-query-prompt", required=True)
@click.option(
    "--model",
    "-m",
    cls=lib.MutuallyExclusiveOption,
    help="Gen AI model name or path",
    mutually_exclusive=["save_prompts"],
)
@click.option(
    "--save-prompts",
    "-s",
    is_flag=True,
    cls=lib.MutuallyExclusiveOption,
    help="Save file specific prompts to json file",
    mutually_exclusive=["model"],
)
@click.option(
    "--reference-existing",
    "-r",
    type=click.Path(exists=True),
    multiple=True,
    help="List of reference files",
)
def generate(
    seed_query_prompt: Union[Path, str],
    model: Union[Path, str],
    save_prompts: bool,
    reference_existing: List[Path],
) -> None:
    """
    \b
    Perform AI based code generation
    \b

    \b
    This command applies generative AI to generate code
    based on specifications given in the prompt
    \b
    """
    if (not model) and (not save_prompts):
        model = os.getenv("CODESCRIBE_MODEL")
        if not model:
            raise click.UsageError(
                "Please provide either the '--model/-m' or '--save-prompts/-p' option"
            )

    api.generate(
        seed_query_prompt,
        model,
        save_prompts,
        [Path(file) for file in reference_existing],
    )


@code_scribe.command(name="update")
@click.argument("filelist", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--seed-prompt",
    "-p",
    help="TOML seed file containing prompts",
)
@click.option(
    "--query-prompt",
    "-q",
    help="Natural language prompt",
)
@click.option(
    "--model",
    "-m",
    required=True,
    default=os.getenv("CODESCRIBE_MODEL"),
    help="Gen AI model name or path",
)
@click.option(
    "--reference-existing",
    "-r",
    type=click.Path(exists=True),
    multiple=True,
    help="List of reference files",
)
def update(
    filelist: List[Path],
    seed_prompt: Path,
    query_prompt: str,
    model: [Path, str],
    reference_existing: List[Path],
) -> None:
    """
    \b
    Perform AI based code update on files
    \b

    \b
    This command applies generative AI to generate code
    based on specifications given in the prompt/
    \b
    """
    if (not seed_prompt) and (not query_prompt):
        raise click.UsageError(
            "Please provide either the '--seed-prompt/-p' or '--query-prompt/-q'"
        )

    api.update(
        [Path(file) for file in filelist],
        model,
        seed_prompt,
        query_prompt,
        [Path(file) for file in reference_existing],
    )


@code_scribe.command(name="inspect")
@click.argument("fortran-files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--query-prompt", "-q", required=True, help="Query prompt")
@click.option(
    "--model",
    "-m",
    cls=lib.MutuallyExclusiveOption,
    help="Gen AI model name or path",
    mutually_exclusive=["save_prompts"],
)
@click.option(
    "--save-prompts",
    "-s",
    is_flag=True,
    cls=lib.MutuallyExclusiveOption,
    help="Save file specific prompts to json file",
    mutually_exclusive=["model"],
)
def inspect(
    fortran_files: List[Path],
    query_prompt: str,
    model: Union[str, Path],
    save_prompts: bool,
) -> None:
    """
    \b
    Perform AI code inspection on files
    \b

    \b
    This command applies generative AI to inspect a list of
    files and answer a query. Results may vary based
    on the the combination of files
    \b
    """
    if (not model) and (not save_prompts):
        model = os.getenv("CODESCRIBE_MODEL")
        if not model:
            raise click.UsageError(
                "Please provide either the '--model/-m' or '--save-prompts/-p' option"
            )

    api.inspect(
        [Path(file) for file in fortran_files],
        query_prompt,
        model,
        save_prompts,
    )


@code_scribe.command(name="format")
@click.argument(
    "seed-prompt-list", nargs=-1, required=True, type=click.Path(exists=True)
)
def format(seed_prompt_list: List[Path]) -> None:
    """
    \b
    Format TOML seed prompt files
    \b

    \b
    This command loads the TOML prompt files
    and formats its contents into a markdown
    format
    \b
    """
    api.format([Path(file) for file in seed_prompt_list])


@code_scribe.command(name="agent")
@click.argument("task", required=True)
@click.option(
    "--model",
    "-m",
    required=True,
    default=os.getenv("CODESCRIBE_MODEL"),
    help="Gen AI model name or path",
)
@click.option(
    "--system",
    "-s",
    default="",
    help="Optional system prompt prepended to the agent instructions",
)
@click.option(
    "--max-iterations",
    "-n",
    default=20,
    show_default=True,
    help="Maximum number of tool-call iterations",
)
@click.option(
    "--show-thinking",
    "-v",
    is_flag=True,
    help="Print each agent iteration's reasoning and tool calls to stdout",
)
def agent(
    task: str,
    model: Union[str, Path],
    system: str,
    max_iterations: int,
    show_thinking: bool,
) -> None:
    """
    \b
    Run an autonomous agent on a task
    \b

    \b
    This command drives a generative AI model through an
    iterative tool-call loop until the task is complete.
    Available tools: read, bash, edit, write, grep, find, ls
    \b
    """
    result = api.agent(task, model, system=system, max_iterations=max_iterations, show_thinking=show_thinking)
    click.echo(result)


@code_scribe.command(name="loop")
@click.argument("spec-file", required=True, type=click.Path(exists=True))
@click.argument("validation-file", required=True, type=click.Path(exists=True))
@click.option(
    "--model",
    "-m",
    required=True,
    default=os.getenv("CODESCRIBE_MODEL"),
    help="Gen AI model name or path",
)
@click.option(
    "--max-rounds",
    "-n",
    default=5,
    show_default=True,
    help="Maximum number of execution/repair rounds",
)
@click.option(
    "--agent-iterations",
    default=12,
    show_default=True,
    help="Maximum tool-call iterations per agent session",
)
@click.option(
    "--workdir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Working directory bound for both agents; defaults to the current directory",
)
@click.option(
    "--show-thinking",
    "-v",
    is_flag=True,
    help="Print each agent iteration's reasoning and tool calls to stdout",
)
def loop(
    spec_file: Path,
    validation_file: Path,
    model: Union[str, Path],
    max_rounds: int,
    agent_iterations: int,
    workdir: Union[str, None],
    show_thinking: bool,
) -> None:
    """
    \b
    Run an execution/repair agent loop
    \b

    \b
    This command runs a validation agent and a repair agent in fresh
    sessions across multiple rounds. Persistent state is inferred only
    from files in the working directory.
    \b
    """
    result = api.loop(
        spec_file=Path(spec_file),
        validation_file=Path(validation_file),
        model=model,
        max_rounds=max_rounds,
        agent_iterations=agent_iterations,
        show_thinking=show_thinking,
        workdir=Path(workdir) if workdir else None,
    )
    click.echo(result)
