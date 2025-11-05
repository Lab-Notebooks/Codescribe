"""Command line interface for Jobrunner"""

import os

from pathlib import Path
from typing import Union, List

from code_scribe import lib


def index(root_dir: Path) -> str:
    """
    API command for creating an index for directory tree
    """
    lib.create_scribe_yaml(root_dir)
    return f"Project structure saved to scribe.yaml."


def draft(fortran_files: List[Path]) -> None:
    """
    API command for creating draft files
    """
    file_index = lib.create_file_indexes()

    for sfile in fortran_files:
        message = lib.annotate_fortran_file(sfile, file_index)
        print(message)


def translate(
    filelist: List[Path],
    seed_prompt: Path,
    model: Union[Path, str],
    save_prompts: bool = False,
) -> None:
    """
    API command for creating draft files
    """
    mapping = lib.create_src_mapping(filelist)
    lib.prompt_translate(mapping, seed_prompt, model=model, save_prompts=save_prompts)


def inspect(
    filelist: List[Path],
    query_prompt: str,
    model: Union[Path, str],
    save_prompts: bool = False,
) -> None:
    """
    API command for inspecting files
    """
    file_index = {}  # lib.create_file_indexes()
    lib.prompt_inspect(
        filelist, query_prompt, file_index, model=model, save_prompts=save_prompts
    )


def generate(
    seed_prompt: Union[Path, str],
    model: Union[Path, str],
    save_prompts: bool = False,
    reference_existing: List[Path] = [],
) -> None:
    """
    API command for generating files
    """
    lib.prompt_generate(
        seed_prompt,
        model=model,
        save_prompts=save_prompts,
        reference_existing=reference_existing,
    )


def update(
    filelist: List[Path],
    seed_prompt: Union[Path, str],
    model: Union[Path, str],
    reference_existing: List[Path] = [],
) -> None:
    """
    API command for updating files
    """
    lib.prompt_update(
        filelist,
        seed_prompt,
        model=model,
        reference_existing=reference_existing,
    )


def format(seed_prompt_list: List[Path]) -> None:
    """
    Format toml files
    """
    for seed_prompt in seed_prompt_list:
        lib.format_seed_prompt(seed_prompt)
