.. |icon| image:: ./media/icon.svg
   :width: 35

###################
 |icon| CodeScribe
###################

|Code style: black|

**********
 Overview
**********

Code-Scribe is a tool designed to facilitate incremental translation of
Fortran codebases into C++ using generative AI. It automates the process
of generating corresponding C++ source files and creating Fortran-C
interfaces, simplifying the integration of Fortran and C++. The tool
also allows users to interface with large language models (LLMs) through
the Transformers API and create custom prompts tailored to the specific
needs of the source code.

Read the paper: https://arxiv.org/abs/2410.24119

**************
 Key Features
**************

-  Incremental Translation: Translate Fortran codebase into C++
   incrementally, creating Fortran-C layers for seamless
   interoperability.

   |fig1|

-  Custom Prompts: Automatically generate prompts for generative AI to
   assist with the conversion process.

-  Language Model Integration: Leverage LLMs through the Transformers
   API to refine the translation and improve accuracy.

   |fig2|

-  Fortran-C Interfaces: Generate the necessary interface layers between
   Fortran and C++ for easy function and subroutine conversion.

*******************
 Statement of Need
*******************

In scientific computing, translating legacy Fortran codebases to C++ is
necessary to leverage modern libraries and ensure performance
portability across various heterogeneous high-performance computing
(HPC) platforms. However, bulk translation of entire codebases often
results in broken functionality and unmanageable complexity. Incremental
translation, which involves creating Fortran-C layers, testing, and
iteratively converting the code, is a more practical approach.
Code-Scribe supports this process by automating the creation of these
interfaces and assisting with generative AI to improve efficiency and
accuracy, ensuring that performance and functionality are maintained
throughout the conversion.

**************
 Installation
**************

At present we recommened installing Code-Scribe in development mode

.. code::

   ./setup develop

Development mode enables testing of features/updates directly from the
source code and is an effective method for debugging. Note that the
``setup`` script relies on ``click``, which can be installed using,

.. code::

   pip install click

The ``code-scribe`` script is installed in ``$HOME/.local/bin``
directory and therfore the environment variable, ``PATH``, should be
updated to include this location for command line use.

*******
 Usage
*******

You can use the `--help` options with every command to get better
understanding of their functionality

.. code::

   ▶ code-scribe --help
   Usage: code-scribe [OPTIONS] COMMAND [ARGS]...

     Software development tool for converting code from Fortran to C++

   Options:
     -v, --version
     --help         Show this message and exit.

   Commands:
     draft      Perform a draft conversion from Fortran to C++
     index      Index Fortran files along a project directory tree
     inspect    Perform a generative AI inspection on Fortran files
     translate  Perform a generative AI conversion of Fortran files

Following is a breif overview of different commands:

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
   huggingface and provide it as an option to ``-m`` or you can simply
   set ``-m openai`` to use OpenAI API to perform code translation. Note
   that ``-m openai`` requires the environemnt variable
   ``OPENAI_API_KEY`` to be set. The ``<prompt.toml>`` is a chat
   template that guides AI to perform code translation using the source
   and draft ``.scribe`` files.

   .. code:: toml

      # Example contents of seed_prompt.toml

      [[chat]]
      role = "user"
      content = "‹Rules and syntax-related instructions for code conversion>"

      [[chat]]
      role = "assistant"
      content = "I am ready. Please give me a test problem."

      [[chat]]
      role = "user"
      content = "<Template of contents in a source file>"

      [[chat]]
      role = "assistant"
      content = "<Desired contents of the converted file. Syntactically correct code>"

      [[chat]]
      role = "user"
      content = "<Append code from a source file>"

#. ``code-scribe translate <filelist> -p <seed_prompt.toml>
   --save-prompts``: This command allows generation of file specific
   json chat template that one can copy/paste to chat interfaces like
   that of ChatGPT to generate the source code. The json files are
   created from the seed prompt file and appended with source and draft
   code.

#. ``code-scribe inspect <filelist> -q <query_prompt> -m
   <model_name_or_path>``: Perform a query on a set of source files
   using a single prompt. This is useful for navigating and
   understanding the source code.

#. ``code-scribe inspect <filelist> -q <query_prompt> --save-prompts``:
   Create a scribe.json that you can copy/paste to chat interfaces.

***************************
 Integrating LLM of Choice
***************************

#. **OpenAI Model**: Code-Scribe supports OpenAI's GPT models (such as
   `gpt-4`, `gpt-3.5-turbo`, etc.) via the OpenAI API. To use OpenAI's
   models, specify `-m openai` in the `translate` command, as shown
   below:

   .. code::

      ▶ code-scribe translate <filelist> -m openai -p <seed_prompt.toml>

Ensure that the environment variable `OPENAI_API_KEY` is set with your
OpenAI API key. You can set it by running the following command in your
terminal:

   .. code::

      export OPENAI_API_KEY="your_openai_api_key_here"

#. **Hugging Face Transformers (TFModel)**: If you want to use a Hugging
   Face model, such as those found on the Hugging Face model hub (e.g.,
   GPT, BERT), you can specify the path to the pre-trained model or use
   a model directly from the Hugging Face library. Code-Scribe supports
   this integration with the `TFModel` class.

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

#. **Llama Model**: Code-Scribe also supports Llama models through the
   `LlamaModel` class. To integrate a Llama model, you need to ensure
   that the model checkpoint directory contains the required files, such
   as the `tokenizer.model`.

   If you have a local Llama model, specify the path to the model
   checkpoint directory like so:

   .. code::

      ▶ code-scribe translate <filelist> -m <path_to_llama_model> -p <seed_prompt.toml>

Ensure that the necessary dependencies are installed for Llama
   models, such as:

   .. code::

      pip install llama

#. **Saving Custom Prompts**: After selecting a model and running the
   translation command, you can also save the generated prompts for
   later use. Use the `--save-prompts` flag to store the prompts in a
   JSON format. This is useful if you want to copy and paste the prompts
   into an external tool, like ChatGPT, for further refinement.

   .. code::

      ▶ code-scribe translate <filelist> -m openai -p <seed_prompt.toml> --save-prompts

   The saved prompts will be stored in a `scribe.json` file.

By following these steps, you can integrate any of the supported
language models into Code-Scribe and use them for incremental
translation of Fortran codebases to C++.

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

.. |Code style: black| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black

.. |fig1| image:: ./media/workflow.png
   :width: 600px

.. |fig2| image:: ./media/engine.png
   :width: 600px
