"""Knobs of the image lane's staging check: a pinned OWLv2 detector's boxes judged as requirements (#1244)."""
from harness.knobs.base import _k

_CONTROLS = "the 15 drawn checker controls (soh staging controls)"

KNOBS = [
    _k("staging_attribute_margin", ["harness/checks/staging.py:ATTRIBUTE_MARGIN"], [0.0, 0.05, 0.1, 0.2],
       lanes=("image",), limit="staging_attribute_margin", unit="share", receipt="knobs", unrecorded=0.0,
       note=f"score by which an attribute's 'is' query must beat its 'not' query on the object's box; on {_CONTROLS} "
            "the right query leads by 0.53 to 0.63 and the planted wrong colour trails by 0.57 (#1244)", grades=True),
    _k("staging_bigger_ratio", ["harness/checks/staging.py:BIGGER_RATIO"], [1.0, 1.2, 1.5, 2.0],
       lanes=("image",), limit="staging_bigger_ratio", unit="factor", receipt="knobs", unrecorded=1.2,
       note=f"box-area ratio over which one object is bigger than another; on {_CONTROLS} the reference is 8.3x and "
            "the planted near-equal pair 0.92x; person agreement decides it (#1244)", grades=True),
    _k("staging_detect_threshold", ["harness/checks/staging.py:DETECT_THRESHOLD"], [0.1, 0.2, 0.3, 0.4, 0.5],
       lanes=("image",), limit="staging_detect_threshold", unit="share", receipt="knobs", unrecorded=0.3,
       note=f"OWLv2 sigmoid score under which a box is no object; on {_CONTROLS} after suppression true boxes score "
            "0.52 to 0.95 and the best false one 0.18; 0.2 to 0.5 pass all 15 and 0.6 drops a true circle (#1244)",
       grades=True),
    _k("staging_device_tolerance", ["harness/checks/staging.py:DEVICE_BOX_TOLERANCE"], [0.001, 0.01, 0.02],
       note="frame share by which an MPS box may differ from the CPU box on the controls; measured 0.0001 with "
            "torch 2.14.0 (#1244)"),
    _k("staging_held_overlap", ["harness/checks/staging.py:HELD_OVERLAP"], [0.25, 0.5, 0.75, 0.9],
       lanes=("image",), limit="staging_held_overlap", unit="share", receipt="knobs", unrecorded=0.5,
       note=f"share of a held object's box that must lie in its holder's box; on {_CONTROLS} held is 1.0 and the "
            "planted star outside 0.0; person agreement decides it (#1244)", grades=True),
    _k("staging_min_agreement", ["harness/checks/staging.py:MIN_AGREEMENT"], [0.7, 0.8, 0.9],
       note="precision and recall a requirement type must reach against a person's labels to count toward the "
            "pass; unmeasured until the first labelled sheet (#1244)"),
    _k("staging_nms_iou", ["harness/checks/staging.py:NMS_IOU"], [0.1, 0.3, 0.5, 0.7],
       lanes=("image",), limit="staging_nms_iou", unit="share", receipt="knobs", unrecorded=0.3,
       note=f"IoU over which a lower box of the same label is dropped; on {_CONTROLS} without it a box over two "
            "circles scores 0.39 and counts a third; 0.1 to 0.5 pass all 15, 0.7 passes 11 (#1244)", grades=True),
    _k("staging_position_margin", ["harness/checks/staging.py:POSITION_MARGIN"], [0.0, 0.05, 0.1, 0.2],
       lanes=("image",), limit="staging_position_margin", unit="share", receipt="knobs", unrecorded=0.1,
       note="share of both boxes' sizes taken off a centre offset before it reads as above; GenEval's "
            "POSITION_THRESHOLD 0.1 (Ghosh et al. 2023) (#1244)", grades=True),
    _k("staging_side_margin", ["harness/checks/staging.py:SIDE_MARGIN"], [0.0, 0.05, 0.1],
       lanes=("image",), limit="staging_side_margin", unit="share", receipt="knobs", unrecorded=0.05,
       note=f"share of the frame width past the centre line a box centre must sit to be on a side; on {_CONTROLS} "
            "the nearest centre is 0.12 from the line (#1244)", grades=True),
]


NOT_GATING = {
    "harness/staging_controls.py:COLOURS[red]": "fill colours of the drawn checker controls; no case or candidate is judged by them (#1244)",
    "harness/staging_controls.py:COLOURS[blue]": "fill colours of the drawn checker controls; no case or candidate is judged by them (#1244)",
    "harness/staging_controls.py:COLOURS[green]": "fill colours of the drawn checker controls; no case or candidate is judged by them (#1244)",
    "harness/staging_controls.py:COLOURS[yellow]": "fill colours of the drawn checker controls; no case or candidate is judged by them (#1244)",
}

NEVER_CUTS = {
    "harness/checks/staging.py:MIN_AGREEMENT": "reports which requirement types fall short of a person's labels; no image is dropped (#1244)",
    "harness/checks/staging.py:DEVICE_BOX_TOLERANCE": "judges whether MPS matches CPU on the controls; no case is cut (#1244)",
}
