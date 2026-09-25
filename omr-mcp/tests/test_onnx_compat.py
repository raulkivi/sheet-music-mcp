"""Tests for rewriting oemer's ONNX model so current onnxruntime accepts it."""

import numpy as np
import onnx
import onnxruntime as ort
import pytest
from onnx import TensorProto, helper, numpy_helper

from omr_mcp.onnx_compat import fix_negative_convtranspose_pads


def _convtranspose_model(path, pads, output_padding=None):
    """1x1 kernel, stride 2 upsampling layer, like the ones in oemer's unet_big."""
    attrs = {"strides": [2, 2], "kernel_shape": [1, 1], "pads": pads}
    if output_padding is not None:
        attrs["output_padding"] = output_padding
    node = helper.make_node("ConvTranspose", ["x", "w", "b"], ["y"], name="up", **attrs)
    graph = helper.make_graph(
        [node],
        "g",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 1, 4, 4])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, None)],
        initializer=[
            numpy_helper.from_array(np.full((1, 1, 1, 1), 2.0, dtype=np.float32), "w"),
            numpy_helper.from_array(np.array([0.5], dtype=np.float32), "b"),
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 9)])
    model.ir_version = 8  # oemer's checkpoints use an old IR; keep the fixture loadable
    onnx.save(model, str(path))
    return path


def _attrs(path):
    [node] = onnx.load(str(path)).graph.node
    return {a.name: list(a.ints) for a in node.attribute if a.ints}


def _run(path, x):
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return session.run(None, {"x": x})[0]


def test_current_onnxruntime_rejects_negative_pads(tmp_path):
    # Documents why the rewrite exists; if this starts passing, it may be removable.
    model = _convtranspose_model(tmp_path / "m.onnx", pads=[0, 0, -1, -1])
    with pytest.raises(Exception, match="pads"):
        ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])


def test_negative_end_pads_become_output_padding(tmp_path):
    model = _convtranspose_model(tmp_path / "m.onnx", pads=[0, 0, -1, -1])
    assert fix_negative_convtranspose_pads(model) == 1
    attrs = _attrs(model)
    assert attrs["pads"] == [0, 0, 0, 0]
    assert attrs["output_padding"] == [1, 1]


def test_rewritten_model_computes_the_padded_output(tmp_path):
    # Stride-2 1x1 transposed conv: w*x on even positions, bias elsewhere,
    # and pad -1 at the end grows the output from 7x7 to 8x8.
    model = _convtranspose_model(tmp_path / "m.onnx", pads=[0, 0, -1, -1])
    fix_negative_convtranspose_pads(model)
    x = np.arange(16, dtype=np.float32).reshape(1, 1, 4, 4)
    expected = np.full((1, 1, 8, 8), 0.5, dtype=np.float32)
    expected[..., ::2, ::2] = 2.0 * x + 0.5
    np.testing.assert_allclose(_run(model, x), expected)


def test_existing_output_padding_is_added_to(tmp_path):
    model = _convtranspose_model(tmp_path / "m.onnx", pads=[0, 0, -1, 0], output_padding=[0, 1])
    fix_negative_convtranspose_pads(model)
    assert _attrs(model)["output_padding"] == [1, 1]


def test_valid_model_is_left_untouched(tmp_path):
    model = _convtranspose_model(tmp_path / "m.onnx", pads=[0, 0, 1, 1])
    before = model.read_bytes()
    assert fix_negative_convtranspose_pads(model) == 0
    assert model.read_bytes() == before


def test_second_run_is_a_no_op(tmp_path):
    model = _convtranspose_model(tmp_path / "m.onnx", pads=[0, 0, -1, -1])
    fix_negative_convtranspose_pads(model)
    after_first = model.read_bytes()
    assert fix_negative_convtranspose_pads(model) == 0
    assert model.read_bytes() == after_first


def test_negative_begin_pads_are_refused(tmp_path):
    # Growing the output at the start has no output_padding equivalent.
    model = _convtranspose_model(tmp_path / "m.onnx", pads=[-1, 0, 0, 0])
    before = model.read_bytes()
    with pytest.raises(ValueError, match="begin"):
        fix_negative_convtranspose_pads(model)
    assert model.read_bytes() == before
