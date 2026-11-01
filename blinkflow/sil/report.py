"""Plain matplotlib command traces and an honest open-loop report."""

import argparse
import json
from pathlib import Path


def command(cmd):
    return f"`{cmd[0]} {cmd[1]:.15g}, {cmd[2]:+.15g}`"


def markdown(data):
    first, impact = data["first_divergence"], data["impact"]
    total = data["totals"]
    lines = [
        "# Purple-box SIL decision comparison", "",
        "This is an **open-loop decision divergence**, not an outcome proof. The recorded "
        "inputs are what the old brain saw. After the first different command the robot would "
        "have been somewhere else; later recorded inputs no longer describe the fixed brain's "
        "world. Outcome proof stays with BlinkFlow's deterministic twin.", "",
        "Replay uses the **pre-existing `microduck_brain.record.replay`** mechanism "
        "(Pollen Robotics / Hugging Face Microduck ecosystem, Apache-2.0), with an observer "
        "that captures each unchanged `Brain.tick` result. New work here is the BlinkFlow "
        "adapter, divergence measurement, report and tests.", "",
        "The incident recording came from the **live simulator**, not a physical robot. "
        "The same recording format supports physical-robot inputs, but no physical robot "
        "was tested here. No simulator, model API, network or key is needed for this replay.", "",
        f"Compared {total['ticks']} ticks over {total['duration_s']:.9f} s. "
        f"Commands differ on {total['command_differences']} ticks; "
        f"states differ on {total['state_differences']} ticks. "
        f"A reproduces the recorded commands with {total['A_vs_recorded_command_differences']} "
        "mismatches at upstream's 1e-4 tolerance.", "",
    ]
    if first:
        lines += [
            f"First exact command divergence: **tick {first['index']} (zero based), "
            f"t = {first['elapsed_s']:.9f} s** after the first recorded tick "
            f"(original input timestamp `{first['t']}`).", "",
            "| brain | command (vx m/s, vyaw rad/s) | state |",
            "|---|---|---|",
            f"| A: before | {command(first['cmd_A'])} | {first['state_A']} |",
            f"| B: fixed | {command(first['cmd_B'])} | {first['state_B']} |", "",
            "Equality is exact on the unrounded command kind, vx and vyaw. "
            "This first change need not be a brake or an in-place turn; "
            "the table states the command actually emitted.", "",
        ]
        tolerant = data["first_divergence_at_upstream_tolerance"]
        if tolerant:
            lines += [
                "For comparison, the first A/B difference exceeding upstream's 1e-4 "
                f"comparison tolerance is tick {tolerant['index']}, "
                f"{tolerant['elapsed_s']:.9f} s: A {command(tolerant['cmd_A'])}, "
                f"B {command(tolerant['cmd_B'])}. This threshold does not replace "
                "the exact first divergence above.", "",
            ]
    else:
        lines += ["**No command divergence** anywhere in this recording; "
                  "there are no first-divergence commands or lead time.", ""]
    if impact:
        citation = impact["citation"]
        lines += [
            f"Recorded contact: BlinkFlow's saved **{citation['reading']} pixel reading**, "
            f"video frame {citation['video_frame']} / shot frame {citation['shot_frame']}, "
            f"**{citation['pixel_contact_elapsed_s']:.3f} s** after the first brain tick. "
            f"Its cited nearest log tick is **{impact['index']}**, displayed as "
            f"{citation['cited_tick_elapsed_s']:.3f} s "
            f"(exact elapsed {impact['elapsed_s']:.9f} s, original timestamp `{impact['t']}`). "
            "The saved evidence is the source of contact; SIL does not measure it again.", "",
        ]
        if data["diverges_before_impact_tick"]:
            lines += [f"The fixed brain's first different command is "
                      f"**{data['lead_to_impact_tick_s']:.9f} s before the cited recorded impact tick** "
                      f"({data['lead_to_pixel_contact_s']:.9f} s before the saved pixel contact). "
                      "This does not establish that contact would be avoided.", ""]
        else:
            lines += ["**The fixed brain does not diverge before the recorded impact tick.** "
                      "This is a negative decision-divergence result, not evidence that the "
                      "fix would prevent contact.", ""]
            if first:
                lines += [f"Signed lead to the cited impact tick: "
                          f"{data['lead_to_impact_tick_s']:.9f} s "
                          "(zero = same tick; negative = after impact).", ""]
        if first and not data["diverges_before_pixel_contact"]:
            lines += ["The first different command is also **not before the saved pixel contact**.", ""]
        lines += [
            "Clock alignment follows BlinkFlow: subtract the log's first input timestamp "
            "for display, then match the evidence's millisecond-rounded tick to the unique "
            "original log row. Brain inputs keep their original timestamps. The nearest "
            f"log tick is {impact['pixel_to_tick_offset_s']:.9f} s after pixel contact; "
            "pixel and tick lead times are therefore reported separately.", "",
            "See [impact.json](impact.json) for the saved citation and source-file hashes.", "",
        ]
    else:
        lines += ["No impact citation supplied; no contact lead time is claimed.", ""]
    lines += [
        "![Emitted command traces](commands.png)", "",
        "The plot shows emitted vx and vyaw, not measured motion. Gaps mean command kind "
        "`none` (no new command), not zero velocity. Stops are drawn at zero. Shading after "
        "first divergence marks the portion whose recorded inputs belong to the old trajectory.", "",
        "`why_B` contains an upstream safety/hold reason when available and is null otherwise. "
        "Upstream exposes no per-tick avoidance explanation; none is fabricated.", "",
        "The bundled [twin sanity](twin-sanity.json) separately checks onset against the "
        "saved before/after deterministic-twin logs. It does not equate the later SIL "
        "commands with the fixed twin's later trajectory.", "",
        "Inputs and source revisions: [provenance.json](provenance.json). "
        "Integrity inventory: [sha256.json](sha256.json).", "",
        "Recheck offline from the repository root: `python3 -B -m blinkflow.sil.recheck examples/purple-box-sil`.", "",
    ]
    return "\n".join(lines)


def generate(data, out):
    # Plotting is optional for replay/recheck; import only for report generation.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10}):
        fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, layout="constrained")
        ticks = data["ticks"]
        times = [t["elapsed_s"] for t in ticks]
        for ax, component, title in zip(axes, (1, 2), ("emitted vx (m/s)", "emitted vyaw (rad/s)")):
            for label, color, style in (("A", "#2563a6", "-"), ("B", "#d66118", "--")):
                values = [t[f"cmd_{label}"][component] if t[f"cmd_{label}"][0] != "none"
                          else float("nan") for t in ticks]
                ax.step(times, values, where="post", color=color, linestyle=style,
                        linewidth=1.3, label=f"{label}: {'before' if label == 'A' else 'fixed'}")
            first = data["first_divergence"]
            if first:
                ax.axvspan(first["elapsed_s"], times[-1], color="#999999", alpha=0.12)
                ax.axvline(first["elapsed_s"], color="#24723c", linestyle=":", label="first exact divergence")
            impact = data["impact"]
            if impact:
                ax.axvline(impact["elapsed_s"], color="#a42525", linestyle="-.", label="cited impact tick")
            ax.set_ylabel(title)
            ax.grid(alpha=0.25)
        axes[0].legend(loc="upper right", fontsize=8)
        axes[-1].set_xlabel("seconds since first recorded brain tick (original times fed unchanged)")
        fig.suptitle("Purple-box: same recorded inputs, two brains\nOpen-loop decisions; no outcome proof")
        fig.savefig(out / "commands.png", dpi=150, metadata={"Software": "BlinkFlow SIL / matplotlib"})
        plt.close(fig)
    (out / "report.md").write_text(markdown(data), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("divergence", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    generate(json.loads(args.divergence.read_text()), args.out or args.divergence.parent)
    print("Wrote report.md and commands.png")


if __name__ == "__main__":
    main()
