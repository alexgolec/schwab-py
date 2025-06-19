#import setuptools
from setuptools import setup, find_packages

with open('README.rst', 'r') as f:
    long_description = f.read()

with open('schwab/version.py', 'r') as f:
    '''Version looks like `version = '1.2.3'`'''
    version = [s.strip() for s in f.read().strip().split('=')][1]
    version = version[1:-1]

setup(
    name='schwab-py',
    version=version,
    author='Alex Golec',
    author_email='bottomless.septic.tank@gmail.com',
    description='Unofficial API wrapper for the Schwab HTTP API',
    long_description=long_description,
    long_description_content_type='text/x-rst',
    url='https://github.com/alexgolec/schwab-py',
    packages=find_packages(),
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Intended Audience :: Developers',
        'Development Status :: 1 - Planning',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Topic :: Office/Business :: Financial :: Investment',
    ],
    python_requires='>=3.10',
    install_requires=[
        'autopep8',
        'authlib',
        'flask',
        'httpx',
        'multiprocess',
        'psutil',
        'python-dateutil',
        'urllib3',
        'websockets'
    ],
    extras_require={
        'dev': [
            'callee',
            'colorama',
            'coverage',
            'nose',
            'pytest',
            'pytz',
            'setuptools',
            'sphinx_rtd_theme',
            'twine',
            'wheel',
        ]
    },
    #packages=find_packages(),            # ← this auto-includes schwab and schwab.scripts
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'schwab-analysis = schwab.scripts.schwab_analysis:main',
            'schwab-refresh-token = schwab.scripts.schwab_refresh_token:main',
            'schwab-fetch-new-token = schwab.scripts.schwab_fetch_new_token:main',
            'schwab-setup-env = schwab.scripts.schwab_setup_env:main',   
            'schwab-package-checker = schwab.scripts.schwab_package_checker:main', 
            # these will not compile in the bin directory.  need to be moved to schwab dir
            # but even then they are not executing correctly.  leaving in bin dir.
            #'schwab-order-codegen = schwab.bin.schwab_order_codegen:main',
            #'schwab-generate-token = schwab.bin.schwab_generate_token:main',
        ],
    },
    keywords='finance trading equities bonds options research',
    project_urls={
        'Documentation': 'https://schwab-py.readthedocs.io/en/latest/',
        'Source': 'https://github.com/alexgolec/schwab-py',
        'Tracker': 'https://github.com/alexgolec/schwab-py/issues',
    },
    license='MIT',

    scripts=[
        'bin/schwab-order-codegen.py',
        'bin/schwab-generate-token.py',
    ],

)

