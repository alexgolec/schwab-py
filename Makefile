dist: clean
	python3 setup.py sdist bdist_wheel

release: clean dist
	python3 -m twine upload dist/*

clean:
	rm -rf build dist docs-build pyschwab.egg-info __pycache__ htmlcov
