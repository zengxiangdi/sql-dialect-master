from backend.core.compatibility import install_compatibility_patches
from backend.core.parser import SQLParser
from backend.core.post_processor import PostProcessor
from backend.core.transpiler import SQLTranspiler


def test_core_transpiler_methods_are_not_legacy_patched():
    install_compatibility_patches()

    assert SQLTranspiler.transpile.__module__ == "backend.core.transpiler"
    assert SQLTranspiler.batch_transpile.__module__ == "backend.core.transpiler"
    assert SQLTranspiler.batch_transpile_async.__module__ == "backend.core.transpiler"
    assert SQLParser.__init__.__module__ == "backend.core.parser"
    assert PostProcessor._replace_function_calls.__module__ == "backend.core.post_processor"


def test_compatibility_installer_is_idempotent():
    install_compatibility_patches()
    first_generate = __import__("backend.core.nl2sql", fromlist=["NL2SQLGenerator"]).NL2SQLGenerator.generate
    install_compatibility_patches()
    second_generate = __import__("backend.core.nl2sql", fromlist=["NL2SQLGenerator"]).NL2SQLGenerator.generate
    assert first_generate is second_generate
