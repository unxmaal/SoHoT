"""Knobs of the craft lane: a model driving a craft app over its own MCP server (#1209)."""
from harness.knobs.base import _k

KNOBS = [
    _k("craft_call_timeout", ["evals/craft.py:CALL_TIMEOUT_S"], [10.0, 30.0, 60.0, 120.0],
       lanes=("craft",), limit="craft_call_timeout_s", unit="s", receipt="knobs",
       note="seconds one tool call, headless build or version probe may take; both apps render on the CPU in "
            "headless mode and VectorCraft calls a request busy after 2 s; unmeasured live until the first run (#1209)"),
    _k("craft_geometry_tolerance", ["evals/craft.py:GEOMETRY_TOLERANCE_PX"], [0.5, 1.0, 2.0, 4.0],
       lanes=("craft",), limit="craft_geometry_tolerance_px", unit="pixels", receipt="knobs",
       note="document units a position or size may sit off its target; the reference script places every node "
            "exactly and the planted misaligned box sits 12 off, so 1.0 separates them twelvefold (#1209)"),
    _k("craft_max_tool_calls", ["evals/craft.py:MAX_TOOL_CALLS"], [40, 80, 120, 200],
       lanes=("craft",), limit="craft_max_tool_calls", unit="calls", receipt="knobs",
       note="tool calls a case may make in all; the svg reference script is 22 commands and the image one 7, so "
            "80 leaves a model 3.6x the longer one (#1209)"),
    _k("craft_output_cap", ["evals/craft.py:OUTPUT_CAP"], [8000, 16000, 32000, 64000],
       lanes=("craft",), limit="craft_output_cap", unit="bytes", receipt="knobs",
       note="characters of one tool result shown to the model; a command list or a deep document.inspect is the "
            "large one; unmeasured live until the first run (#1209)"),
    _k("craft_render_difference", ["evals/craft.py:RENDER_DIFFERENCE_MAX"], [0.005, 0.01, 0.02, 0.05],
       lanes=("craft",), limit="craft_render_difference", unit="share", receipt="knobs",
       note="mean RGB difference from the reference render under which a render is reported matching; secondary, "
            "never the pass; the reference against itself is 0; no near-miss render measured yet (#1209)"),
    _k("craft_steps_scale", ["evals/runners/craft.py:MAX_STEPS_SCALE"], [0.5, 1.0, 1.5, 2.0],
       lanes=("craft",), limit="craft_steps_scale", unit="factor", receipt="knobs",
       note="multiplies every craft run book's own max_steps, set at twice its reference script's command count "
            "(svg 44 for 22, image 16 for 7) (#1209)"),
]

NOT_GATING = {
    "evals/craft_mcp.py:Client.close(grace)": "seconds a craft app's server gets to exit after the document was read; "
                                              "no case's outcome waits on it",
}
