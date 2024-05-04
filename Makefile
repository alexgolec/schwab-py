test:
	python -m pytest tests/

fix:
	autopep8 --in-place -r -a schwab
	#autopep8 --in-place -r -a tests
	#autopep8 --in-place -r -a examples

coverage:
	python3 -m coverage run --source=schwab -m nose
	python3 -m coverage html

dist: clean
	python3 setup.py sdist bdist_wheel

# TODO: Reinstate tests before releasing
#release: clean test dist
release: clean dist
	python3 -m twine upload dist/*

clean:
	rm -rf build dist docs-build schwab_py.egg-info __pycache__ htmlcov
