test:
	uv run pytest tests/

fix:
	uv run autopep8 --in-place -r -a schwab

coverage:
	uv run coverage run -m pytest tests/
	uv run coverage report
	uv run coverage html

dist: clean
	uv build

# TODO: Reinstate tests before releasing
#release: clean test dist
release: clean dist
	uv publish

clean:
	rm -rf build dist docs-build schwab_py.egg-info __pycache__ htmlcov
