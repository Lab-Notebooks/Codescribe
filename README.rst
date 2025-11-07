.. |icon| image:: ./media/icon.svg
   :width: 35

###################
 |icon| CodeScribe
###################

|Code style: black|

**********
 Overview
**********

Code-Scribe is an AI-assisted framework designed to streamline
Fortran-to-C++ code translation and facilitate the development and
maintenance of scientific codebases. It automates the process of
generating corresponding C++ source files and creating Fortran-C++
interfaces, simplifying the integration of Fortran and C++. The tool
allows users to interface with large language models (LLMs) through the
API endpoints and locally through the Transformers library, and enables
the creation of custom prompts tailored to the specific needs of the source
code. Code-Scribe empowers research software engineers by complementing
existing tools like OpenAI Codex and addressing the niche requirements
of scientific software development.

***********
 Resources
***********

-  Papers:

   -  https://arxiv.org/abs/2410.24119

-  Tutorials:

   -  https://anl.box.com/s/zv3zdbphqprdz8rjh1c84xpeqd8yg32u
   -  https://github.com/akashdhruv/codescribe-tutorial.git

-  Use cases:

   -  https://erf.readthedocs.io/en/latest/CouplingToNoahMP.html

**************
 Key Features
**************

-  Incremental Translation: Translate Fortran codebases into C++
   incrementally, creating Fortran-C++ layers for seamless
   interoperability.

   |fig1|

-  Custom Prompts: Automatically generate prompts for generative AI to
   assist with the conversion process.

-  Language Model Integration: Leverage LLMs through the Transformers
   API to refine the translation and improve accuracy.

   |fig2|

-  Fortran-C++ Interfaces: Generate the necessary interface layers between
   Fortran and C++ for easy function and subroutine conversion.

-  Code Generation and Update: Create new source files or modify
   existing ones from natural-language prompts.

*******************
 Statement of Need
*******************

In scientific computing, translating legacy Fortran codebases to C++ is
necessary to leverage modern libraries and ensure performance
portability across various heterogeneous high-performance computing
(HPC) platforms. However, bulk translation of entire codebases often
results in broken functionality and unmanageable complexity. Incremental
translation, which involves creating Fortran-C++ layers, testing, and
iteratively converting the code, is a more practical approach.
Code-Scribe supports this process by automating the creation of these
interfaces and assisting with generative AI to improve efficiency and
accuracy, ensuring that performance and functionality are maintained
throughout the conversion. Additionally, Code-Scribe facilitates code
generation and updates, enabling users to create new applications or
modify existing files seamlessly.

**************
 Installation
**************

At present, we recommend installing Code-Scribe in a virtual
environment:

.. code::

   python3 -m venv env
   source env/bin/activate
   pip install --upgrade pip

And install Code-Scribe using ``pip`` in editable mode:

.. code::

   pip install -e .

Editable mode enables testing of features/updates directly from the
source code and is an effective method for debugging.

*******
 Usage
*******

You can use the `--help` option with every command to get a better
understanding of their functionality.

.. code::

   ▶ code-scribe --help
   Usage: code-scribe [OPTIONS] COMMAND [ARGS]...

     Software development tool for converting code from Fortran to C++

   Options:
     -v, --version
     --help         Show this message and exit.

   Commands:
     draft      Perform a draft conversion from Fortran to C++
     format     Format TOML seed prompt files
     generate   Perform AI-based code generation
     index      Index Fortran files along a project directory tree
     inspect    Perform AI code inspection on files
     translate  Perform AI-based code conversion of Fortran files
     update     Perform AI-based code update on files

Following is a brief overview of different commands:

#. ``code-scribe index <project_root_dir>`` - Parses the project
   directory tree and creates a ``scribe.yaml`` file at each node along
   the directory tree. These YAML files contain metadata about
   functions, modules, and subroutines in the source files. This
   information is used during the conversion process to guide LLM models
   in understanding the structure of the code.

   .. code:: yaml

      # Example contents of scribe.yaml
      directory: src
      files:
        module1.f90:
          modules:
            - module1
          subroutines:
            - subroutine1
            - subroutine2
          functions:
            - function1

        module2.f90:
          modules: []
          subroutines:
            - subroutineA
          functions:
            - functionB

#. ``code-scribe draft <filelist>``: Takes a list of files and generates
   draft versions of the corresponding C++ files. The draft files are
   saved with a ``.scribe`` extension and include prompts tailored to
   each statement in the original source code.

#. ``code-scribe translate <filelist> -m <model_name_or_path> -p
   <seed_prompt.toml>``: This command performs neural translation using
   generative AI. You can either download a model locally from
   Hugging Face and provide it as an option to ``-m`` or you can simply
   set ``-m openai-gpt-4o`` to use the OpenAI API to perform code
   translation. Note that ``-m openai-gpt-4o`` requires the environment
   variable ``OPENAI_API_KEY`` to be set. The ``<prompt.toml>`` is a
   chat template that guides AI to perform code translation using the
   source and draft ``.scribe`` files.

   .. code:: toml

      # Example contents of seed_prompt.toml

      [[chat.user]]
      content = "‹Rules and syntax-related instructions for code conversion>"

      [[chat.assistant]]
      content = "I am ready. Please give me a test problem."

      [[chat.user]]
      content = "<Template of contents in a source file>"

      [[chat.assistant]]
      content = "<Desired contents of the converted file. Syntactically correct code>"

      [[chat.user]]
      content = "<Append code from a source file>"

#. ``code-scribe translate <filelist> -p <seed_prompt.toml>
   --save-prompts``: This command allows the generation of file-specific
   JSON chat templates that one can copy/paste to chat interfaces like
   that of ChatGPT to generate the source code. The JSON files are
   created from the seed prompt file and appended with source and draft
   code.

#. ``code-scribe inspect <filelist> -q <query_prompt> --save-prompts``:
   Create a scribe.json that you can copy/paste to chat interfaces.

#. ``code-scribe inspect <filelist> -q <query_prompt> -m
   <model_name_or_path>``: Perform a query on a set of source files
   using a single prompt. This is useful for navigating and
   understanding the source code.

#. ``code-scribe generate <seed_prompt> -m <model_name_or_path>``:
   Generate new source files or applications based on specifications in
   the prompt.

#. ``code-scribe generate "<natural_language_prompt>" -m
   <model_name_or_path> -r <reference_file1> -r
   <reference_file2>``: Generate new source files or applications based
   on specifications in the prompt. **This implementation offers great
   flexibility in generating source code and specification files.**

#. ``code-scribe update <filelist> -p <seed_prompt.toml> -m
   <model_name_or_path>``: Modify or extend existing source files using
   seed prompt files.

#. ``code-scribe update <filelist> -p "<natural_language_prompt>" -r
   <reference_file1> -r <reference_file2> -m <model_name_or_path>``:
   This command allows for updating files using natural language prompts
   and reference files. **This implementation offers great flexibility
   in updating existing files.**

***************************
 Integrating LLM of Choice
***************************

#. **OpenAI Model**: Code-Scribe supports OpenAI's GPT models (such as
   `gpt-4`, `gpt-3.5-turbo`, etc.) via the OpenAI API. To use OpenAI's
   models, specify `-m openai-gpt-4o` when executing the commands, as
   shown below:

   .. code::

      ▶ code-scribe translate <filelist> -m openai-gpt-4o -p <seed_prompt.toml>

   Ensure that the environment variable `OPENAI_API_KEY` is set with
   your OpenAI API key. You can set it by running the following command
   in your terminal:

   .. code::

      export OPENAI_API_KEY="your_openai_api_key_here"

   And you have installed the OpenAI library:

   .. code::

      pip install openai

#. **Hugging Face Transformers (TFModel)**: If you want to use a Hugging
   Face model, such as those found on the Hugging Face model hub (e.g.,
   Mistral, Llama), you can specify the path to the pre-trained model or
   use a model directly from the Hugging Face library. Code-Scribe
   supports this integration with the `TFModel` class.

   To use a Hugging Face model, first install the necessary libraries if
   not already installed:

   .. code::

      pip install transformers torch

   Then specify the path to the pre-trained model using the `-m` flag in
   the command. For example, to use a GPT-2 model:

   .. code::

      ▶ code-scribe translate <filelist> -m <path_to_model> -p <seed_prompt.toml>

   You can download a model from the Hugging Face model hub by visiting
   `https://huggingface.co/models` and choosing one that fits your
   needs.

#. **ARGO Models**: Code-Scribe also supports integration with Argonne's
   ARGO models, such as `argo-gpt4o`. These models are accessible on the
   Argonne network by setting the environment variables `ARGO_USER` and
   `ARGO_API_ENDPOINT`. To use ARGO models, specify `-m argo-gpt4o` or
   any other ARGO-supported model of your choice when executing
   commands, as shown below:

   .. code::

      ▶ code-scribe translate <filelist> -m argo-gpt4o -p <seed_prompt.toml>

   Ensure that the environment variables `ARGO_USER` and
   `ARGO_API_ENDPOINT` are set correctly. For example:

   .. code::

      export ARGO_USER="your_argo_username"
      export ARGO_API_ENDPOINT="argo_api_endpoint"

   ARGO models are recommended for users with access to the Argonne
   network.

#. **Saving Custom Prompts**: Instead of selecting a model and running
   the commands interactively, you can also save the generated prompts
   for later use. Use the `--save-prompts` flag to store the prompts in
   a JSON format. This is useful if you want to copy and paste the
   prompts into an external tool, like ChatGPT, for further refinement.

   .. code::

      ▶ code-scribe translate <filelist> -p <seed_prompt.toml> --save-prompts

   The saved prompts will be stored in a `scribe.json` file.

***********************
 Environment Variables
***********************

To streamline the usage of Code-Scribe and avoid repeatedly specifying
the `-m` flag for model selection, you can set the environment variable
`CODESCRIBE_MODEL` to the desired model name or path. For example:

.. code::

   export CODESCRIBE_MODEL="argo-gpt4o"

This will automatically use the specified model for all commands without
requiring the `-m` flag.

Additionally, to archive interactions with LLMs for downstream analysis
or debugging, you can set the `CODESCRIBE_ARCHIVE` environment variable
to a directory path where the interactions will be stored:

.. code::

   export CODESCRIBE_ARCHIVE="/path/to/archive/directory"

By setting these environment variables, you can simplify your workflow
and ensure that all interactions are logged for future reference.

By following these steps, you can integrate any of the supported
language models into Code-Scribe and use them for incremental
translation of Fortran codebases to C++. Please see the source file
`lib/_llm.py` to view the source code.

**********
 Citation
**********

.. code::

   @software{akash_dhruv_2024_13879406,
   author       = {Akash Dhruv},
   title        = {akashdhruv/CodeScribe: 2024.09},
   month        = oct,
   year         = 2024,
   publisher    = {Zenodo},
   version      = {2024.09},
   doi          = {10.5281/zenodo.13879406},
   url          = {https://github.com/akashdhruv/CodeScribe}
   }

.. code::

   @conference{dhruv_dubey_2025_3732775,
   author       = {Akash Dhruv and Anshu Dubey},
   title        = {Leveraging Large Language Models for Code Translation and Software Development in Scientific Computing},
   year         = 2025,
   doi          = {10.1145/3732775.3733572},
   url          = {https://doi.org/10.1145/3732775.3733572},
   publisher    = {Association for Computing Machinery},
   booktitle    = {Proceedings of the Platform for Advanced Scientific Computing Conference}
   }

.. |Code style: black| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black

.. |fig1| image:: ./media/workflow.png
   :width: 600px

.. |fig2| image:: ./media/engine.png
   :width: 600px
