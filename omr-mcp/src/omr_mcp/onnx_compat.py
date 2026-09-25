"""Makes oemer's exported ONNX models loadable by current onnxruntime.

oemer's unet_big checkpoint (converted from TensorFlow) has ConvTranspose
layers with negative end pads, e.g. ``pads=[0, 0, -1, -1]``. A negative end
pad grows the output by that many rows/columns. onnxruntime <= 1.19 accepted
this; newer releases reject it during shape inference ("Attribute pads must
not contain negative values"), and Python 3.13+ wheels only exist for those
newer releases.

ConvTranspose's ``output_padding`` attribute grows the output at the same
(high-index) side, so ``pads=[b, -e]`` is rewritten to ``pads=[b, 0]`` plus
``output_padding += e``. Verified against onnxruntime 1.18.1 on the real
unet_big model: identical predictions, max absolute difference < 1e-6.
"""

import os
import tempfile
from pathlib import Path

import onnx
from onnx import helper


def _int_list(node: onnx.NodeProto, name: str) -> list[int] | None:
    for attr in node.attribute:
        if attr.name == name:
            return list(attr.ints)
    return None


def _set_int_list(node: onnx.NodeProto, name: str, values: list[int]) -> None:
    for attr in list(node.attribute):
        if attr.name == name:
            node.attribute.remove(attr)
    node.attribute.append(helper.make_attribute(name, values))


def _begin_end_pads(node: onnx.NodeProto) -> tuple[list[int], list[int]]:
    pads = _int_list(node, "pads") or []
    half = len(pads) // 2
    return pads[:half], pads[half:]


def _check_begin_pads(node: onnx.NodeProto) -> None:
    begin, _ = _begin_end_pads(node)
    if any(p < 0 for p in begin):
        raise ValueError(f"{node.name}: negative begin pads {begin} have no output_padding equivalent")


def _fix_node(node: onnx.NodeProto) -> bool:
    begin, end = _begin_end_pads(node)
    if all(p >= 0 for p in end):
        return False
    output_padding = _int_list(node, "output_padding") or [0] * len(end)
    _set_int_list(node, "pads", begin + [max(0, p) for p in end])
    _set_int_list(node, "output_padding", [op + max(0, -p) for op, p in zip(output_padding, end)])
    return True


def _save_atomically(model: onnx.ModelProto, path: Path) -> None:
    # A crash mid-write must not leave oemer with a truncated checkpoint.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".onnx.tmp")
    os.close(fd)
    try:
        onnx.save(model, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def fix_negative_convtranspose_pads(model_path: Path | str) -> int:
    """Rewrite negative ConvTranspose end pads in place; return how many nodes changed.

    Leaves the file untouched (and returns 0) when nothing needs fixing, so it
    is cheap to call before every recognition.
    """
    path = Path(model_path)
    model = onnx.load(str(path))
    candidates = [n for n in model.graph.node if n.op_type == "ConvTranspose"]
    # Validate every node before changing any, so a refusal leaves the model as it was.
    for node in candidates:
        _check_begin_pads(node)
    fixed = sum(_fix_node(node) for node in candidates)
    if fixed:
        _save_atomically(model, path)
    return fixed
