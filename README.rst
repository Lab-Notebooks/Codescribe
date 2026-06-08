.. |icon| image:: ./media/icon.svg
   :width: 35

###################
 |icon| Codescribe
###################

|Code style: black|

Codescribe is an AI-assisted framework for scientific software development.
It started as an incremental **Fortran → C++** translation tool, and now also
supports code inspection, generation, updating, and tool-using agent workflows.

- Paper: https://arxiv.org/abs/2410.24119
- Demo (Zenodo): https://doi.org/10.5281/zenodo.18853292
- Tutorial repo: https://github.com/akashdhruv/codescribe-tutorial

**************
 Key features
**************

- Incremental Fortran → C++ translation with interface-layer support.
- Prompt-driven workflows: inspect / generate / update / translate.
- Agentic workflows with tools: ``read``, ``bash``, ``edit``, ``write``.
- Multiple backends: OpenAI, Anthropic, OpenAI-compatible endpoints, ARGO,
  and local Transformers checkpoints.

**************
 Installation
**************

.. code:: bash

   python3 -m venv env
   source env/bin/activate
   pip install --upgrade pip
   pip install -e .

*******
 Usage
*******

.. code:: bash

   code-scribe --help

Primary commands:

- ``index``: index Fortran source trees and write ``scribe.yaml`` metadata.
- ``draft``: create ``.scribe`` draft files (prompt scaffolding).
- ``translate``: LLM-assisted Fortran → C++ translation.
- ``inspect``: ask questions about files.
- ``generate``: create new code from prompts.
- ``update``: modify existing code from prompts.
- ``agent``: run a tool-using coding agent on a task.
- ``loop``: run repeated *bounded* agent sessions over a task file.

Agent docs:

- ``docs/agent.md`` (architecture + bounded-mode policy)

Model/backends docs:

- ``docs/models.md``

***************************
 Model backend quickstart
***************************

Recommended default: **OpenAI-compatible endpoints** using the ``oaic-`` prefix.

.. code:: bash

   export OPENAI_COMP_BASEURL="http://localhost:11434/v1"
   export OPENAI_COMP_PROVIDER="ollama"
   export OPENAI_COMP_APIKEY="placeholder"

   code-scribe inspect README.rst -m oaic-llama3.1 -q "Summarize this repo."

***********************
 Environment variables
***********************

- ``OPENAI_API_KEY`` for ``openai-*``
- ``ANTHROPIC_API_KEY`` for ``anthropic-*``
- ``ANTHROPIC_BASE_URL`` (optional) for ``anthropic-*``
- ``ARGO_USER`` and ``ARGO_API_ENDPOINT`` for ``argo-*``
- ``OPENAI_COMP_BASEURL``, ``OPENAI_COMP_PROVIDER``, ``OPENAI_COMP_APIKEY`` for ``oaic-*``
- ``CODESCRIBE_ARCHIVE`` to save prompt/response transcripts

**********
 Citation
**********

See `citation.cff`.

.. |Code style: black| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black
