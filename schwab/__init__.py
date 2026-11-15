import warnings as _warnings

from . import auth
from . import client
#from . import contrib
from . import debug
from . import orders
from . import streaming
from . import utils

from .version import version as __version__

LOG_REDACTOR = debug.LogRedactor()


class V2DeprecationWarning(FutureWarning):
    '''Emitted on import while schwab-py is on the 1.x line, announcing
    the upcoming 2.0 series and its library interface changes.

    The warning is attributed to ``schwab/__init__.py`` rather than the
    importing module so that it fires once per process and so module
    filters work: to suppress it, either set

    ``PYTHONWARNINGS="ignore::FutureWarning:schwab"``

    before starting your program, or call
    ``warnings.filterwarnings('ignore', category=FutureWarning,
    module='schwab')`` in code before importing schwab.
    '''


# This warning belongs to the 1.x line: remove it when the version is
# bumped to 2.0.0a1.
_warnings.warn(
        'schwab-py 2.0 is coming with new features and improvements '
        '(see https://schwab-py.readthedocs.io/en/latest/v2.html for '
        'the transition plan and migration notes). The release will '
        'also include library interface changes: to stay on the 1.x '
        'line, pin "schwab-py<2.0" in your package manager.',
        V2DeprecationWarning)
