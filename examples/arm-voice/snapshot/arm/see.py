"""Visual-prompt adapter for a stylized arm that SAM does not detect by name."""
from blinkflow import sam, see as original

# Marked from the first rendered image, not from MuJoCo states/contact geometry.
# Every replay starts at the same pose. No contact frame is marked.
ARM_BOX = (108, 180, 480, 580)
PROMPT = "<0f>1<|box;x1=108;y1=180;x2=480;y2=580;w=960;h=720|>"
_installed = False


def configure():
    global _installed
    if _installed: return
    _installed=True
    track=sam.track
    def seeded(clip,concept,frames,raw_path=None):
        r=track(clip,PROMPT if concept=="robot arm" else concept,frames,raw_path)
        r["concept"]=concept
        return r
    sam.track=seeded
    # One continuous six-second shot: the box refers to frame 0, not a later piece.
    original.PIECE_FRAMES=10000
