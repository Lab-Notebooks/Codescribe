"""Command line interface for Jobrunner"""

import os
from code_scribe import lib


def index(root_dir):
    """
    API command for creating an index for directory tree
    """
    lib.create_scribe_yaml(root_dir)
    return f"Project structure saved to scribe.yaml."


def draft(fortran_files):
    """
    API command for creating a draft files
    """
    file_index = lib.create_file_indexes()

    for sfile in fortran_files:
        message = lib.annotate_fortran_file(sfile, file_index)
        print(message)


def translate(filelist, seed_prompt, model, save_prompts=False):
    """
    API command for creating a draft files
    """
    mapping = lib.create_src_mapping(filelist)
    lib.prompt_translate(mapping, seed_prompt, model=model, save_prompts=save_prompts)


def inspect(filelist, query_prompt, model, save_prompts=False):
    """
    API command for creating a draft files
    """
    file_index = {}  # lib.create_file_indexes()
    lib.prompt_inspect(
        filelist, query_prompt, file_index, model=model, save_prompts=save_prompts
    )
