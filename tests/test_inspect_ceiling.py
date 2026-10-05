"""The inspect ceiling is per machine, not the 32 GB mini's on every Mac. #355."""
from harness import inspect as ins
from harness.memory import Accelerator

GIB = 1024 ** 3


def test_the_machine_it_was_measured_on_keeps_its_ceiling():
    """Negative control: the 32 GB mini still reads 22 GiB."""
    assert ins.ceiling_bytes(Accelerator("unified", 32.0, 32.0)) == 22 * GIB


def test_a_96_gb_mac_is_not_held_to_the_minis_ceiling():
    """The Studio read 22 GiB and reopened none of 173 too-big refusals."""
    assert ins.ceiling_bytes(Accelerator("unified", 96.0, 96.0)) == 66 * GIB


def test_a_discrete_card_is_still_its_vram():
    assert ins.ceiling_bytes(Accelerator("discrete", 12.0, 10.5)) == 12 * GIB


def test_an_unknown_size_falls_back_to_the_measured_constant():
    assert ins.ceiling_bytes(Accelerator("unified", 0.0, 0.0)) == ins.MEMORY_CEILING
