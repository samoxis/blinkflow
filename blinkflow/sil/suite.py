"""Frozen-code suite: discrete decisions on the shared open-loop prefix."""

import argparse
from collections import Counter
import json
from pathlib import Path

from .replay import compare_traces, sha256, trace, write_json

DEFAULT_SUITE = Path(__file__).resolve().parents[2] / "examples" / "suite-sil"
CASE_ORDER = ("b3", "b4", "b6", "b7", "b8", "b9", "b10", "b11")
CLASSES = ("discrete-decision-before-impact", "continuous-only", "no-divergence-before-impact")
POLICY = (
    "Classify on the prefix ending at the first exact different command. "
    "discrete-decision-before-impact requires a pre-impact first different command and "
    "B's differential stop/in-place turn or protective state while A stays forward, "
    "with no earlier different command. Earlier continuous steering makes the result "
    "continuous-only (inconclusive), even if a later state differs before impact. "
    "Without a command difference strictly before the cited impact tick, classify "
    "no-divergence-before-impact. No numerical threshold replaces exact equality."
)


def stop_or_turn(cmd):
    """Steering while walking is not an in-place turn."""
    return cmd[0] == "stop" or (cmd[0] == "move" and cmd[1] == 0 and cmd[2] != 0)


def analyze(data):
    """Measure every onset, but do not promote post-divergence decisions to proof."""
    if data["impact"] is None:
        raise ValueError("suite classification requires a saved pixel impact/fall citation")
    ticks, first, impact = data["ticks"], data["first_divergence"], data["impact"]
    pixel = impact["citation"]["pixel_contact_elapsed_s"]  # Phase 1 compatibility key; also used for falls.
    prefix_end = first["index"] if first else ticks[-1]["index"]

    def point(row):
        if row is None:
            return None
        i = row["index"]
        return {**row,
                "previous_state_A": ticks[i - 1]["state_A"] if i else None,
                "previous_state_B": ticks[i - 1]["state_B"] if i else None,
                "lead_to_impact_tick_s": impact["t"] - row["t"],
                "lead_to_saved_pixel_event_s": pixel - row["elapsed_s"],
                "within_shared_command_prefix": i <= prefix_end}

    def find(predicate):
        return next((t for t in ticks if predicate(t)), None)

    state = find(lambda t: t["state_A"] != t["state_B"])
    raw_stop = find(lambda t: stop_or_turn(t["cmd_B"]))
    after_forward = None
    seen_forward = False
    for row in ticks:
        if seen_forward and stop_or_turn(row["cmd_B"]):
            after_forward = row
            break
        seen_forward |= row["state_B"] == "forward"
    decisive = find(lambda t: t["state_A"] == "forward" and t["cmd_A"] != t["cmd_B"]
                    and stop_or_turn(t["cmd_B"]))
    protective = find(lambda t: t["state_A"] == "forward"
                      and t["state_B"] in ("brake", "turn", "bigturn", "hold"))
    preimpact = first is not None and first["t"] < impact["t"]
    supported = next((t for t in (protective, decisive)
                      if t is not None and t["index"] <= prefix_end and t["t"] < impact["t"]), None)
    classification = CLASSES[0] if preimpact and supported else CLASSES[1] if preimpact else CLASSES[2]
    return {
        "classification": classification, "classification_policy": POLICY,
        "first_exact_divergence": point(first), "first_state_divergence": point(state),
        "first_B_stop_or_turn_command": point(raw_stop),
        "first_B_stop_or_turn_after_forward": point(after_forward),
        "first_B_differential_stop_or_turn": point(decisive),
        "first_B_protective_state_while_A_forward": point(protective),
        "supported_discrete_decision": point(supported) if classification == CLASSES[0] else None,
        "shared_command_prefix_last_index": prefix_end,
        "pixel_event_kind": impact["citation"]["event_kind"],
        "pixel_event_elapsed_s": pixel, "impact_tick_index": impact["index"],
        "impact_tick_elapsed_s": impact["elapsed_s"],
        "pixel_event_before_impact_tick_s": impact["elapsed_s"] - pixel,
        "interpretation": (
            "B changes a discrete decision on the shared prefix before the saved event; "
            "this remains decision evidence, not evidence of avoiding the outcome."
            if classification == CLASSES[0] else
            "Continuous-only (inconclusive): later state/stop differences are outside "
            "the shared prefix and cannot establish the fixed trajectory."
            if classification == CLASSES[1] else
            "No command divergence strictly before the cited impact tick; no prevention claim."
        ),
    }


def measure_case(case):
    case = Path(case)
    metadata = json.loads((case / "case.json").read_text())
    if metadata["status"] != "processed":
        raise ValueError("cannot replay an unprocessed case")
    recording = case / "run.jsonl.gz"
    impact = json.loads((case / "impact.json").read_text())
    a, b = trace(recording, case / "brain-before"), trace(recording, case / "brain-after")
    data = compare_traces(recording, a, b, impact)
    if data["totals"]["A_vs_recorded_command_differences"] or data["totals"]["A_vs_recorded_state_differences"]:
        raise ValueError(f"{metadata['bug']}: buggy brain does not reproduce its incident commands/states")
    data["suite_analysis"] = analyze(data)
    data["case"] = {k: metadata[k] for k in ("bug", "scene", "fix", "kept_attempt", "event_kind")}
    return data


def load_cases(root):
    root = Path(root)
    suite = json.loads((root / "suite.json").read_text())
    if tuple(suite["case_order"]) != CASE_ORDER:
        raise ValueError("suite must retain all eight frozen-code cases in authoritative table order")
    cases = []
    for bug in CASE_ORDER:
        metadata = json.loads((root / bug / "case.json").read_text())
        if metadata["bug"] != bug or metadata["status"] not in ("processed", "unprocessed"):
            raise ValueError("suite case identity/status does not match its ordered slot")
        if metadata["status"] == "unprocessed" and not metadata.get("reason"):
            raise ValueError("unprocessed case must include its exact reason")
        cases.append(metadata)
    return suite, cases


def command(cmd):
    return f"{cmd[0]} {cmd[1]!r}, {cmd[2]:+}"


def onset(point):
    if point is None:
        return "none"
    return f"{point['elapsed_s']:.6f} s (tick {point['index']})"


def summary_markdown(cases, results):
    counts = Counter(data["suite_analysis"]["classification"] for data in results.values())
    lines = ["# Frozen-code suite SIL results", "",
             "Open-loop decision divergence only; no contact/fall prevention or physical-robot "
             "outcome is proved. All inputs are saved deterministic-twin recordings. "
             "Replay is the pre-existing microduck_brain.record.replay mechanism "
             "(Pollen Robotics / Hugging Face Microduck ecosystem, Apache-2.0).", "",
             "Cases remain in the frozen-code table's order; each uses the stored buggy base "
             "and the actual kept fix, without tuning or replacing a fix. Seven of these eight "
             "mutations repeated an earlier suite mutation; this is not an independent sample.", "",
             POLICY, "",
             "`continuous-only` names the inconclusive evidence at first command divergence, "
             "not an assertion that no later state ever differs. Later state/stop observations "
             "are retained and explicitly marked outside the shared prefix.", "",
             "All times below are seconds since the first recorded input, ticks zero based. "
             "Lead column: exact / state / differential B stop-or-turn, relative to the cited "
             "nearest impact tick. Pixel-event leads and the signed rounding/alignment offsets "
             "are retained in each report and JSON. `*` means after an earlier command divergence.", "",
             "| bug | scene | kept fix | first exact divergence | first state divergence | B's decisive command | lead before impact: exact / state / B command | class |",
             "|---|---|---|---|---|---|---|---|"]
    for metadata in cases:
        bug = metadata["bug"]
        if bug not in results:
            lines.append(f"| {bug} | {metadata.get('scene', 'unknown')} | unavailable | — | — | — | — | unprocessed: {metadata['reason']} |")
            continue
        d = results[bug]["suite_analysis"]
        first, state, decisive = (d[k] for k in ("first_exact_divergence", "first_state_divergence", "first_B_differential_stop_or_turn"))
        state_text = onset(state)
        if state:
            state_text += f"; A {state['state_A']} / B {state['state_B']}" + ("*" if not state["within_shared_command_prefix"] else "")
        cmd_text = "none" if decisive is None else f"{command(decisive['cmd_B'])} at {onset(decisive)}" + ("*" if not decisive["within_shared_command_prefix"] else "")
        leads = " / ".join("n/a" if p is None else f"{p['lead_to_impact_tick_s']:.6f}" for p in (first, state, decisive))
        lines.append(f"| [{bug}]({bug}/report.md) | {metadata['scene']} | {metadata['fix']} | {onset(first)} | {state_text} | {cmd_text} | {leads} s | {d['classification']} |")
    lines += ["", "; ".join(f"{label}: **{counts[label]}**" for label in CLASSES)
              + f"; unprocessed: **{len(cases) - len(results)}**.", "",
              "Every run begins with a common startup stop. It is recorded as B's absolute "
              "first stop/turn, but never counted as a changed protective decision. The table "
              "uses B's first differential stop/in-place turn while A remains forward.", "",
              "The impact/fall comes from each before-run's saved pixel evidence, not the "
              "scorer times in the historical suite table. Contact citations already name a "
              "nearest log tick; pixel falls do not, so the same nearest-tick rule is applied "
              "and that derivation is recorded. No new pixel measurement was made.", "",
              "Phase 1 purple-box remains **continuous-only (inconclusive)**: the first exact "
              "change is steering at 2.104866302 s. Its later state differences cannot undo "
              "that earlier divergence. The Phase 1 bundle is unchanged.", "",
              "Offline: `python -B -S -m sil.recheck examples/suite-sil`. "
              "Integrity and original source citations are in `sha256.json` and `suite.json`. "
              "New work is the adapter, divergence measurement, classification, report and tests. "
              "No model API calls or tuning; replay cost $0.", ""]
    return "\n".join(lines)


def report_markdown(metadata, data):
    analysis = data["suite_analysis"]
    event = data["impact"]
    citation = event["citation"]
    lines = [f"# {metadata['bug']} — {metadata['scene']} SIL", "",
             "**Open-loop decision divergence, not an outcome proof.** Recorded inputs "
             "belong to the buggy brain. After its first different command, the fixed robot "
             "would be elsewhere and later inputs no longer describe its world. Outcome "
             "proof stays with BlinkFlow's deterministic twin; no physical robot was tested.", "",
             "Uses unchanged, pre-existing `microduck_brain.record.replay` (Pollen Robotics / "
             "Hugging Face Microduck ecosystem, Apache-2.0) with the Phase 1 observer. New work "
             "is the adapter, measurements, classification, report and tests.", "",
             f"Class: **{analysis['classification']}**. {analysis['interpretation']}", "",
             f"Kept fix (attempt {metadata['kept_attempt']}): {metadata['fix']}. "
             "The exact saved patch is [change.diff](change.diff). "
             "Source revisions and hashes are in [case.json](case.json).", "",
             f"Saved pixel **{citation['event_kind']}**, reading `{citation['reading']}`, "
             f"frame {citation['video_frame']}: elapsed {citation['pixel_contact_elapsed_s']:.6f} s. "
             f"Nearest impact tick {event['index']}: elapsed {event['elapsed_s']:.6f} s, "
             f"original timestamp {event['t']!r}. {citation['tick_alignment']} "
             f"Tick minus pixel-event time: {event['pixel_to_tick_offset_s']:+.6f} s.", "",
             "The selected saved event excerpt is in [event.json](event.json); its original "
             "evidence-file path and SHA-256 are recorded. `pixel_contact_elapsed_s` is the "
             "legacy Phase 1 compatibility key and denotes the selected pixel **fall** when "
             "event_kind is fall. No fall is relabelled as a contact.", "",
             "| measurement | elapsed time / tick | A state → B state | commands A / B (vx m/s, vyaw rad/s) | lead to cited impact tick / saved pixel event | shared prefix |",
             "|---|---|---|---|---|---|"]
    for title, key in (
        ("First exact divergence", "first_exact_divergence"),
        ("First state divergence", "first_state_divergence"),
        ("B first stop/turn, including startup", "first_B_stop_or_turn_command"),
        ("B first stop/turn after entering forward", "first_B_stop_or_turn_after_forward"),
        ("B first differential stop/turn while A forward", "first_B_differential_stop_or_turn"),
    ):
        p = analysis[key]
        if p is None:
            lines.append(f"| {title} | none | — | — | n/a | — |")
        else:
            lines.append(f"| {title} | {onset(p)} | {p['state_A']} → {p['state_B']} | "
                         f"`{command(p['cmd_A'])}` / `{command(p['cmd_B'])}` | "
                         f"{p['lead_to_impact_tick_s']:.6f} / {p['lead_to_saved_pixel_event_s']:.6f} s | "
                         f"{'yes' if p['within_shared_command_prefix'] else 'no: after first command divergence'} |")
    lines += ["", POLICY, "",
              "The initial shared startup stop is not a differential decision. "
              "A turn means `move` with vx=0 and nonzero vyaw; steering with vx>0 stays continuous. "
              "All comparisons use exact unrounded command values, without tuning a threshold.", "",
              f"Ticks: {data['totals']['ticks']}; exact command differences: "
              f"{data['totals']['command_differences']}; state differences: "
              f"{data['totals']['state_differences']}. A matches the saved commands at "
              "upstream's 1e-4 recording tolerance and all saved states. `why_B` is only "
              "the upstream safety/hold reason; no avoidance explanation is invented.", "",
              "![Emitted commands and decision markers](commands.png)", "",
              "Traces show emitted commands, not observed motion. Gaps represent `none`. "
              "Shading starts at exact divergence; later state/command markers are retained "
              "without claiming their later inputs are counterfactual reality.", "",
              "Offline recheck: `python -B -S -m sil.recheck examples/suite-sil`. "
              "No API, simulator, installation, key file or network is needed; cost $0.", ""]
    return "\n".join(lines)


def plot_case(metadata, data, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    analysis = data["suite_analysis"]
    times = [t["elapsed_s"] for t in data["ticks"]]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 9}):
        fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, layout="constrained")
        for ax, component, ylabel in zip(axes, (1, 2), ("emitted vx (m/s)", "emitted vyaw (rad/s)")):
            for label, color, style in (("A", "#2563a6", "-"), ("B", "#d66118", "--")):
                values = [r[f"cmd_{label}"][component] if r[f"cmd_{label}"][0] != "none"
                          else float("nan") for r in data["ticks"]]
                ax.step(times, values, where="post", color=color, linestyle=style, label=label)
            first = analysis["first_exact_divergence"]
            if first:
                ax.axvspan(first["elapsed_s"], times[-1], color="grey", alpha=0.12)
            for key, color, style, title in (
                ("first_exact_divergence", "#25813b", ":", "first exact command"),
                ("first_state_divergence", "#7542a2", "--", "first state difference"),
                ("first_B_differential_stop_or_turn", "#da9800", "-.", "B differential stop/turn"),
            ):
                point = analysis[key]
                if point:
                    ax.axvline(point["elapsed_s"], color=color, linestyle=style, linewidth=1.1, label=title)
            ax.axvline(data["impact"]["elapsed_s"], color="#b32323", label="saved impact/fall tick")
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.2)
        axes[0].legend(loc="upper right", fontsize=7, ncol=2)
        axes[-1].set_xlabel("seconds since first recorded input; original timestamps fed unchanged")
        fig.suptitle(f"{metadata['bug']} / {metadata['scene']}: {analysis['classification']}\n"
                     "Open-loop decisions only; shaded inputs belong to the old trajectory")
        fig.savefig(Path(out) / "commands.png", dpi=150, metadata={"Software": "BlinkFlow SIL / matplotlib"})
        plt.close(fig)


def rederive_suite(root):
    _, cases = load_cases(root)
    results = {m["bug"]: measure_case(Path(root) / m["bug"]) for m in cases if m["status"] == "processed"}
    return cases, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", nargs="?", default=DEFAULT_SUITE, type=Path)
    parser.add_argument("--out", default=Path(".cache/suite-replay"), type=Path)
    parser.add_argument("--plots", action="store_true", help="also render PNGs; requires matplotlib")
    args = parser.parse_args()
    if args.out.resolve() == args.suite.resolve():
        parser.error("choose a separate output directory; do not overwrite the published bundle")
    cases, results = rederive_suite(args.suite)
    args.out.mkdir(parents=True, exist_ok=True)
    for metadata in cases:
        bug = metadata["bug"]
        if bug not in results:
            continue
        dest = args.out / bug
        write_json(dest / "divergence.json", results[bug])
        (dest / "report.md").write_text(report_markdown(metadata, results[bug]), encoding="utf-8")
        if args.plots:
            plot_case(metadata, results[bug], dest)
        print(f"{bug}: {results[bug]['suite_analysis']['classification']} {sha256(dest / 'divergence.json')}")
    (args.out / "summary.md").write_text(summary_markdown(cases, results), encoding="utf-8")


if __name__ == "__main__":
    main()
