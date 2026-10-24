"""Knobs of the checks that grade a reply (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("chrome_render_timeout", ["harness/checks/render.py:CHROME_TIMEOUT_S"], [30.0, 60.0, 120.0, 300.0],
       lanes=("web",), limit="chrome_render_timeout_s", unit="s", receipt="knobs", note="seconds headless Chrome may take to screenshot a page (#693)", unrecorded=60.0),
    _k("claims_control_recall", ["evals/claims_report.py:CONTROL_RECALL"], [0.8, 0.9, 0.95],
       note="control recall under which the claims report suspects the matcher, not the model (#661)"),
    _k("claims_match_threshold", ["harness/checks/claims.py:MATCH_THRESHOLD"], [0.3, 0.4, 0.5, 0.6, 0.7],
       lanes=("claims",), limit="claims_match_threshold", unit="share", receipt="knobs", note="word overlap at which an emitted claim is a reviewed one (#654)"),
    _k("claims_min_recall", ["harness/checks/claims.py:MIN_RECALL"], [0.25, 0.5, 0.75, 1.0],
       lanes=("claims",), limit="claims_min_recall", unit="share", receipt="knobs", note="share of a case's good claims a reply must recover (#654)"),
    _k("claims_recall_weight", ["harness/checks/claims.py:RECALL_WEIGHT"], [0.25, 0.5, 0.75],
       note="weight of a missed claim against a fabricated one in claims_balanced; a ranking weight, not a grade; infovore's call, equal until then (#791)"),
    _k("code_check_timeout", ["harness/checks/code.py:DEFAULT_TIMEOUT"], [5.0, 15.0, 30.0, 60.0, 120.0],
       lanes=("code",), limit="code_check_timeout_s", unit="s", receipt="knobs",
       note="wall clock a code answer and its checks may run; a case may set params.check_timeout (#693)", unrecorded=15.0),
    _k("svg_angle_tolerance", ["harness/checks/svg.py:ANGLE_TOLERANCE"], [2.0, 4.0, 8.0],
       note="svg: degrees a clock hand may point off its true angle in a structure assertion (#1050)"),
    _k("svg_coord_tolerance", ["harness/checks/svg.py:COORD_TOLERANCE"], [0.5, 1.0, 2.0],
       note="svg: user units a coordinate may sit from where a structure assertion puts it (#1050)"),
    _k("svg_render_timeout", ["harness/checks/render.py:SVG_TIMEOUT_S"], [10.0, 30.0, 60.0, 120.0],
       lanes=("svg",), limit="svg_render_timeout_s", unit="s", receipt="knobs", note="seconds rsvg-convert may take to draw one SVG (#693)", unrecorded=30.0),
]

NOT_GATING = {
    "harness/checks/image.py:SMALL_EDGE": "edge in pixels under which an image check adds a small-image warning; "
                                          "pass or fail comes from its other checks (#734)",
    "evals/private.py:MIN_FRAGMENT": "which private text the leak scan looks for; never a lane's outcome (#654)",
    "evals/analysis/laya_finetune.py:MAX_CHARS": "characters of an exchange the offline #970 embedding control reads, infovore's embed MAX_CHARS; never a lane's outcome (#970)",
    "evals/analysis/laya_finetune.py:_embed_fitter.vectors->tok(max_length)": "bge-small's own 512-token window in the offline #970 analysis; never a lane's outcome (#970)",
    "harness/checks/image.py:ImageResult.stddev": "a measured result's value before it is measured (#706)",
    "harness/checks/video.py:VideoResult.motion": "a measured result's value before it is measured (#706)",
    "harness/checks/video.py:VideoResult.stddev": "a measured result's value before it is measured (#706)",
    "harness/checks/ocr.py:OcrResult.cer": "a measured result's value before it is measured (#706)",
    "harness/checks/ocr.py:check->OcrResult(cer)": "a measured result's value, as reported (#706)",
}
