"""Verify every bundled byte and re-derive decision divergence offline."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile

from .replay import json_bytes, replay, sha256, write_json
from .sanity import check as twin_check

DEFAULT_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "purple-box-sil"
DEFAULT_SUITE = DEFAULT_EXAMPLE.parent / "suite-sil"


def inventory(example):
    example = Path(example)
    files = {}
    for path in sorted(example.rglob("*")):
        if path.is_symlink():
            raise ValueError("example must not contain symlinks")
        if path.is_file() and path != example / "sha256.json":
            files[path.relative_to(example).as_posix()] = sha256(path)
    return files


def write_manifest(example):
    write_json(Path(example) / "sha256.json", {"algorithm": "sha256", "files": inventory(example)})


def verify_inventory(example):
    expected = json.loads((example / "sha256.json").read_text())
    if expected.get("algorithm") != "sha256" or not isinstance(expected.get("files"), dict):
        raise ValueError("invalid SHA-256 manifest")
    for name in expected["files"]:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or p.as_posix() != name:
            raise ValueError("manifest paths must be canonical relative POSIX paths")
    actual = inventory(example)
    if actual != expected["files"]:
        missing = sorted(expected["files"].keys() - actual.keys())
        extra = sorted(actual.keys() - expected["files"].keys())
        changed = sorted(k for k in actual.keys() & expected["files"].keys()
                         if actual[k] != expected["files"][k])
        raise ValueError(f"bundle integrity mismatch: missing={missing}, extra={extra}, changed={changed}")
    return actual


def recheck(example=DEFAULT_EXAMPLE):
    example = Path(example).resolve()
    hashes = verify_inventory(example)
    impact = json.loads((example / "impact.json").read_text())
    result = replay(example / "run.jsonl.gz", example / "brain-before", example / "brain-after", impact)
    with tempfile.TemporaryDirectory(prefix="blinkflow-sil-") as temp:
        generated = Path(temp) / "divergence.json"
        write_json(generated, result)
        actual = sha256(generated)
        if actual != hashes["divergence.json"]:
            raise ValueError(f"re-derived divergence mismatch: {actual}")
    sanity = twin_check(example / "sanity" / "before.jsonl.gz", example / "sanity" / "after.jsonl.gz",
                        example / "brain-before", example / "brain-after")
    if json_bytes(sanity) != (example / "twin-sanity.json").read_bytes():
        raise ValueError("re-derived twin sanity differs from bundled result")
    return {"passed": True, "verified_files": len(hashes), "divergence_sha256": actual,
            "twin_sanity_passed": True}


def recheck_suite_case(case):
    from .suite import measure_case, report_markdown

    case = Path(case).resolve()
    hashes = verify_inventory(case)
    metadata = json.loads((case / "case.json").read_text())
    if metadata["status"] == "unprocessed":
        if not metadata.get("reason"):
            raise ValueError("unprocessed case must retain its exact reason")
        return {"bug": metadata["bug"], "status": "unprocessed", "reason": metadata["reason"]}, None
    if metadata["status"] != "processed":
        raise ValueError("unknown suite case status")
    # Check the published log sanitization and saved event binding, without the originals.
    raw = gzip.decompress((case / "run.jsonl.gz").read_bytes())
    header, _, payload = raw.partition(b"\n")
    provenance = metadata["recording_provenance"]
    if json.loads(header) != provenance["public_header"] or json.loads(header)["config"] != "brain.toml":
        raise ValueError("recording header/provenance mismatch")
    if (hashlib.sha256(payload).hexdigest() != provenance["tick_payload_sha256"]
            or sha256(case / "run.jsonl.gz") != provenance["public_compressed_sha256"]
            or provenance["original_compressed_sha256"] != metadata["source_files"]["before_recording"]["sha256"]):
        raise ValueError("recording payload/provenance mismatch")
    event = json.loads((case / "event.json").read_text())
    impact = json.loads((case / "impact.json").read_text())
    selected = event["selected_event"]
    if (event["source"] != metadata["source_files"]["pixel_evidence"]
            or impact["source_evidence_sha256"] != event["source"]["sha256"]
            or impact["pixel_contact_elapsed_s"] != selected["brain_s"]
            or impact["video_frame"] != selected["frame"]
            or impact["shot_frame"] != selected["shot_frame"]
            or impact["reading"] != selected["reading"]
            or impact["event_kind"] != event["event_kind"]
            or impact["event_kind"] != metadata["event_kind"]):
        raise ValueError("saved pixel event citation mismatch")
    if "brain_tick" in selected and (impact["cited_tick_elapsed_s"] != selected["brain_tick"]["t"]
                                     or impact["recorded_cmd"] != selected["brain_tick"]["cmd"]):
        raise ValueError("saved contact tick citation mismatch")
    if sha256(case / "change.diff") != metadata["source_files"]["kept_patch"]["sha256"]:
        raise ValueError("kept fix patch provenance mismatch")
    data = measure_case(case)
    digest = hashlib.sha256(json_bytes(data)).hexdigest()
    if digest != hashes["divergence.json"]:
        raise ValueError(f"{metadata['bug']}: re-derived suite divergence hash mismatch")
    if report_markdown(metadata, data).encode() != (case / "report.md").read_bytes():
        raise ValueError(f"{metadata['bug']}: re-derived report differs")
    for label, side in (("A", "before"), ("B", "after")):
        source = case / f"brain-{side}"
        wanted = {"LICENSE", "NOTICE", *data[f"brain_{label}_sha256"]}
        actual = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
        if wanted != actual:
            raise ValueError("suite snapshot does not contain exactly the imported source closure")
    return {"bug": metadata["bug"], "status": "processed", "passed": True,
            "divergence_sha256": digest, "classification": data["suite_analysis"]["classification"]}, data


def recheck_suite(root=DEFAULT_SUITE):
    from collections import Counter
    from .suite import POLICY, load_cases, summary_markdown

    root = Path(root).resolve()
    hashes = verify_inventory(root)
    suite, cases = load_cases(root)
    if suite["classification_policy"] != POLICY:
        raise ValueError("published suite classification policy differs from implementation")
    checks, results = [], {}
    for metadata in cases:
        checked, data = recheck_suite_case(root / metadata["bug"])
        checks.append(checked)
        if data is not None:
            results[metadata["bug"]] = data
    if summary_markdown(cases, results).encode() != (root / "summary.md").read_bytes():
        raise ValueError("re-derived suite summary differs")
    return {"passed": True, "verified_files": len(hashes), "cases": checks,
            "processed": len(results), "unprocessed": len(cases) - len(results),
            "classes": dict(Counter(d["suite_analysis"]["classification"] for d in results.values()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", nargs="?", type=Path,
                        help="Phase 1 example, suite root, or one suite case; default checks both phases")
    args = parser.parse_args()
    if args.example is None:
        result = recheck(DEFAULT_EXAMPLE)
        result["suite"] = recheck_suite(DEFAULT_SUITE)
    elif (args.example / "suite.json").is_file():
        result = recheck_suite(args.example)
    elif (args.example / "case.json").is_file():
        result, _ = recheck_suite_case(args.example)
    else:
        result = recheck(args.example)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
