"""The diffusers image loader falls back when AutoPipeline's table lags. #380."""
import pytest

from harness import image_diffusers


class _Auto:
    def __init__(self, exc):
        self.exc = exc

    def from_pretrained(self, model, **kw):
        raise self.exc


class _Any:
    @staticmethod
    def from_pretrained(model, **kw):
        return ("generic", model, kw)


class _Diffusers:
    def __init__(self, exc):
        self.AutoPipelineForText2Image = _Auto(exc)
        self.DiffusionPipeline = _Any


def test_a_pipeline_missing_from_autopipelines_table_loads_by_its_own_class():
    exc = ValueError("AutoPipeline can't find a pipeline linked to PRXPixelPipeline for None")
    got = image_diffusers.load(_Diffusers(exc), "Photoroom/prxpixel-t2i", safety_checker=None)
    assert got == ("generic", "Photoroom/prxpixel-t2i", {"safety_checker": None})


def test_any_other_load_error_still_raises():
    with pytest.raises(ValueError, match="only set"):
        image_diffusers.load(_Diffusers(ValueError("but only set() were passed")), "o/x")


def test_a_non_turbo_model_gets_the_pipelines_own_sampling():
    """#401: prxpixel refused guidance 0.0, which suits only distilled turbo models."""
    assert image_diffusers.sampling("Photoroom/prxpixel-t2i", None, None) == {}


def test_a_turbo_model_keeps_the_turbo_settings():
    assert image_diffusers.sampling("stabilityai/sdxl-turbo", None, None) == {
        "num_inference_steps": 4, "guidance_scale": 0.0}


def test_an_explicit_setting_always_wins():
    assert image_diffusers.sampling("o/x", 20, 3.5) == {
        "num_inference_steps": 20, "guidance_scale": 3.5}
