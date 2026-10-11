"""Knobs of the checks that grade a reply (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("chrome_render_timeout", ["harness/checks/render.py:CHROME_TIMEOUT_S"], [30.0, 60.0, 120.0, 300.0],
       lanes=("web",), limit="chrome_render_timeout_s", receipt="knobs", note="seconds headless Chrome may take to screenshot a page (#693)", unrecorded=60.0),
    _k("claims_match_threshold", ["harness/checks/claims.py:MATCH_THRESHOLD"], [0.3, 0.4, 0.5, 0.6, 0.7],
       lanes=("claims",), limit="claims_match_threshold", receipt="knobs", note="word overlap at which an emitted claim is a reviewed one (#654)"),
    _k("claims_min_recall", ["harness/checks/claims.py:MIN_RECALL"], [0.25, 0.5, 0.75, 1.0],
       lanes=("claims",), limit="claims_min_recall", receipt="knobs", note="share of a case's good claims a reply must recover (#654)"),
    _k("code_check_timeout", ["harness/checks/code.py:DEFAULT_TIMEOUT"], [5.0, 15.0, 30.0, 60.0, 120.0],
       lanes=("code",), limit="code_check_timeout_s", receipt="knobs",
       note="wall clock a code answer and its checks may run; a case may set params.check_timeout (#693)", unrecorded=15.0),
    _k("svg_render_timeout", ["harness/checks/render.py:SVG_TIMEOUT_S"], [10.0, 30.0, 60.0, 120.0],
       lanes=("svg",), limit="svg_render_timeout_s", receipt="knobs", note="seconds rsvg-convert may take to draw one SVG (#693)", unrecorded=30.0),
]

NOT_GATING = {
    "evals/private.py:MIN_FRAGMENT": "which private text the leak scan looks for; never a lane's outcome (#654)",
    "harness/checks/image.py:ImageResult.stddev": "a measured result's value before it is measured (#706)",
    "harness/checks/video.py:VideoResult.motion": "a measured result's value before it is measured (#706)",
    "harness/checks/video.py:VideoResult.stddev": "a measured result's value before it is measured (#706)",
    "harness/checks/ocr.py:OcrResult.cer": "a measured result's value before it is measured (#706)",
    "harness/checks/ocr.py:check->OcrResult(cer)": "a measured result's value, as reported (#706)",
}
