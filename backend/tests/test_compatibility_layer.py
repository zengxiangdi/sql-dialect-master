from backend.core import install_compatibility_patches
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.transpiler import SQLTranspiler


def test_compatibility_install_is_idempotent():
    install_compatibility_patches()
    install_compatibility_patches()

    result = SQLTranspiler().transpile("SELECT 1", "mysql", "postgres")
    assert result.success

    generated = NL2SQLGenerator().generate("find products with price greater than 10", "postgres")
    assert generated.success
