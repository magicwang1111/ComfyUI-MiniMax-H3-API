import importlib.util
import sys
import types
from pathlib import Path

import numpy


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "comfyui_minimax_h3_api"


def _load_module(name):
    full_name = f"{PACKAGE_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(full_name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE_NAME] = package

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT / "tests" / "output")
folder_paths.get_save_image_path = lambda prefix, output: (output, "test", 1, "", prefix)
sys.modules.setdefault("folder_paths", folder_paths)

try:
    import torch  # noqa: F401
except ModuleNotFoundError:
    torch = types.ModuleType("torch")

    class Tensor:
        pass

    torch.Tensor = Tensor
    torch.as_tensor = numpy.asarray
    sys.modules["torch"] = torch

client = _load_module("client")
media = _load_module("media")
nodes = _load_module("nodes")
sys.modules["minimax_test_client"] = client
sys.modules["minimax_test_media"] = media
sys.modules["minimax_test_nodes"] = nodes
