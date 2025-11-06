"""Command line interface for Jobrunner"""

# Standard libraries
import os
from pathlib import Path
from typing import Union, List

# Feature libraries
import click

from code_scribe.cli import code_scribe
from code_scribe import api
from code_scribe import lib


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
@click.argument("seed-prompt", required=True)
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
    seed_prompt: Union[Path, str],
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
    based on specifications given in the prompt/
    \b
    """
    if (not model) and (not save_prompts):
        model = os.getenv("CODESCRIBE_MODEL")
        if not model:
            raise click.UsageError(
                "Please provide either the '--model/-m' or '--save-prompts/-p' option"
            )

    api.generate(
        seed_prompt,
        model,
        save_prompts,
        [Path(file) for file in reference_existing],
    )


@code_scribe.command(name="update")
@click.argument("filelist", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--seed-prompt",
    "-p",
    required=True,
    help="TOML seed file containt prompts",
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
    seed_prompt: Union[Path, str],
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
    api.update(
        [Path(file) for file in filelist],
        seed_prompt,
        model,
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
    Perform AI code inspection on Fortran files
    \b

    \b
    This command applies generative AI to inspect a list of
    Fortran files and answer a query. Results may vary based
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
