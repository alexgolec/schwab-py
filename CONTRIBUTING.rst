=============================
Contributing to ``schwab-py``
=============================

Fixing a bug? Adding a feature? Just cleaning up for the sake of cleaning up? 
Great! No improvement is too small for me, and I'm always happy to take pull 
requests. Read this guide to learn how to set up your environment so you can 
contribute.

------------------------------
Setting up the Dev Environment
------------------------------

This project uses `uv <https://docs.astral.sh/uv/>`_ to manage dependencies 
and the development environment. Once uv is installed, create a virtual 
environment and install the project (in editable mode) together with the 
development dependencies:

.. code-block:: shell

  uv sync

Finally, verify everything works by running tests:

.. code-block:: shell

  make test

At this point you can make your changes.

Note that ``uv run`` and ``make`` execute commands inside the project 
environment automatically, so there is no need to activate the virtual 
environment yourself. If you prefer to activate it anyway, it lives in 
``.venv/`` in the project directory.

----------------------
Development Guidelines
----------------------

+++++++++++++++++
Test your changes
+++++++++++++++++

This project aims for high test coverage. All changes must be properly tested, 
and we will accept no PRs that lack appropriate unit testing. We also expect 
existing tests to pass. You can run your tests using: 

.. code-block:: shell

  make test

++++++++++++++++++
Document your code
++++++++++++++++++

Documentation is how users learn to use your code, and no feature is complete 
without a full description of how to use it. If your PR changes external-facing 
interfaces, or if it alters semantics, the changes must be thoroughly described 
in the docstrings of the affected components. If your change adds a substantial 
new module, a new section in the documentation may be justified. 

Documentation is built using `Sphinx <https://www.sphinx-doc.org/en/master/>`__:

.. code-block:: shell

  uv run --group docs sphinx-build docs/ docs-build
