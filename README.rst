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
- Agentic workflows with tools: ``read``, ``glob``, ``bash``, ``edit``, ``write``.
- Bounded loop mode: repeated execution → review cycles with durable state.
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
- ``inspect``: ask questions about files (bounded read-only agent).
- ``generate``: create new code from prompts.
- ``update``: modify existing code from prompts.
- ``format``: render TOML seed prompt files to markdown.
- ``agent``: run a tool-using coding agent on a task (unbounded).
- ``loop``: run repeated bounded execution → review cycles over a task file.

Key flags:

- ``agent --verbose/-v``: stream per-iteration tool calls to stdout.
- ``agent --log / --log-path PATH``: write TOML diagnostics to disk.
- ``loop --workdir DIR``: set the root directory the agent is bounded to.
- ``loop --agent-loops/-nloop N``: number of execution → review cycles (default 5).
- ``loop --agent-iterations/-niter N``: tool-call budget per cycle (default 12).

Docs:

- ``docs/agent.md`` — agent architecture and bounded-mode policy
- ``docs/loop.md`` — loop mode internals and on-disk artifacts
- ``docs/tools.md`` — tool implementations (read/glob/bash/edit/write)
- ``docs/models.md`` — model backends and environment variables

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

- ``CODESCRIBE_MODEL``: default model name used when ``-m`` is omitted.
- ``CODESCRIBE_MAX_TOKENS``: maximum output tokens per model reply (default: 24576).
- ``OPENAI_API_KEY`` for ``openai-*``
- ``ANTHROPIC_API_KEY`` for ``anthropic-*``
- ``ANTHROPIC_BASE_URL`` (optional) for ``anthropic-*``
- ``ARGO_USER`` and ``ARGO_API_ENDPOINT`` for ``argo-*``
- ``OPENAI_COMP_BASEURL``, ``OPENAI_COMP_PROVIDER``, ``OPENAI_COMP_APIKEY`` for ``oaic-*``

**********
 Citation
**********

See `citation.cff`.

.. |Code style: black| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black
