"""Command line and run orchestration (spec sections 3, 9 and 10)."""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ingest import mapping, publish, reader, rows, writer
from ingest.agent import SimulatedAgent
from ingest.errors import RunError
from ingest.models import Warning
from ingest.ops import MemoryGuard, StageTimer, setup_log, total_memory_mb

STRONG_ROW_WARNINGS = {"NO_CONTACT_CHANNEL", "DUPLICATE_CONFLICT"}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RunError("USAGE", f"Wrong arguments: {message}. Usage: python -m ingest run --input <file.csv>", "start")


def _percent(text: str) -> float:
    try:
        value = float(text.rstrip("%"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text}") from None
    if not 0 <= value <= 100:
        raise argparse.ArgumentTypeError(f"threshold outside 0 to 100: {text}")
    return value


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = _Parser(prog="python -m ingest")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    run = sub.add_parser("run")
    run.add_argument("--input", required=True, type=Path)
    run.add_argument("--output", default=Path("runs"), type=Path)
    run.add_argument("--dictionary", default=Path("mappings/synonyms.json"), type=Path)
    run.add_argument("--approve", type=Path)
    run.add_argument("--missing-contact-threshold", default=3.0, type=_percent)
    run.add_argument("--rejection-threshold", default=10.0, type=_percent)
    run.add_argument("--memory-warn", default=50.0, type=_percent)
    run.add_argument("--memory-stop", default=80.0, type=_percent)
    run.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def _prepare_output(output: Path) -> None:
    try:
        output.mkdir(parents=True, exist_ok=True)
        probe = output / ".write_check"
        probe.write_text("")
        probe.unlink()
    except OSError as exc:
        raise RunError("OUTPUT_NOT_WRITABLE", f"Output folder cannot be written: {output} ({exc.strerror or exc})",
                       "write") from None


class _NoErrors(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.ERROR


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = _parse(argv)
        _prepare_output(args.output)
    except RunError as err:
        print(err, file=sys.stderr)
        return err.exit_code
    now_utc = datetime.now(timezone.utc)
    run_id = now_utc.strftime("run_%Y-%m-%d_%H%M%SZ")
    log = setup_log(args.output / "logs" / f"{run_id}.log")
    for handler in log.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.addFilter(_NoErrors())
    temp = args.output / f".tmp_{run_id}"
    state = {"stage": "read"}
    try:
        return _run(args, now_utc, run_id, temp, log, state)
    except RunError as err:
        return _fail(err, log, temp, args, run_id)
    except OSError as exc:
        if state["stage"] == "write":
            err = RunError("OUTPUT_NOT_WRITABLE", f"Output cannot be written in {args.output} ({exc})", "write")
        else:
            err = RunError("INTERNAL_ERROR", f"Unexpected error in stage {state['stage']}; see the log", state["stage"])
        return _fail(err, log, temp, args, run_id, exc)
    except Exception as exc:  # no traceback reaches the operator (D17)
        err = RunError("INTERNAL_ERROR", f"Unexpected error in stage {state['stage']}; see the log", state["stage"])
        return _fail(err, log, temp, args, run_id, exc)
    finally:
        for handler in list(log.handlers):
            handler.close()
            log.removeHandler(handler)


def _fail(err: RunError, log, temp: Path, args, run_id: str, exc: Exception | None = None) -> int:
    detail = f" ({type(exc).__name__})" if exc else ""
    log.error(err.message + detail, extra={"stage": err.stage, "code": err.code})
    publish.discard(temp, args.debug, "failed_" + run_id[len("run_"):])
    print(err, file=sys.stderr)
    return err.exit_code


def _run(args, now_utc: datetime, run_id: str, temp: Path, log, state: dict) -> int:
    timer = StageTimer()
    run_time = now_utc.astimezone()
    total_mb = total_memory_mb()
    guard = MemoryGuard(args.memory_warn, args.memory_stop, total_mb)
    memory_warnings: list[Warning] = []

    def check():
        for code in guard.check(state["stage"]):
            memory_warnings.append(Warning(None, None, code))
            log.warning(code.replace("_", " ").lower(), extra={"stage": state["stage"], "code": code})
    log.info(f"Run {run_id} started", extra={"stage": "start", "code": "-"})

    with timer.stage("read"):
        state["stage"] = "read"
        read = reader.read_file(args.input, check)
        state["stage"] = "map"
        try:
            dictionary = mapping.load_dictionary(args.dictionary)
        except (OSError, ValueError):
            raise RunError("USAGE", f"Wrong arguments: dictionary cannot be read: {args.dictionary}", "start") from None
        maps, map_warnings = mapping.resolve_mapping(
            read.header, [r.cells for r in read.records[:1000]], args.dictionary, args.output,
            args.input.name, SimulatedAgent(dictionary), args.approve, now_utc)
        state["stage"] = "read"
        check()
    _log_stage(log, "read", timer)

    with timer.stage("clean"):
        state["stage"] = "clean"
        read.warnings = map_warnings + read.warnings
        outcome = rows.process(read, maps, run_time, check)
        check()
    _log_stage(log, "clean", timer)

    thresholds = {"missing_contact_pct": args.missing_contact_threshold, "rejection_pct": args.rejection_threshold,
                  "memory_warn_pct": args.memory_warn, "memory_stop_pct": args.memory_stop}
    common = dict(run_id=run_id, run_started_at=run_time.isoformat(timespec="seconds"),
                  export_date=datetime.fromtimestamp(args.input.stat().st_mtime).date().isoformat(),
                  input_name=args.input.name, rows_received=read.rows_received, maps=maps, outcome=outcome,
                  total_memory_mb=_round(total_mb), thresholds=thresholds)
    outcome.warnings.extend(memory_warnings + rows.run_flags(outcome, read.rows_received, thresholds))

    with timer.stage("write"):
        state["stage"] = "write"
        temp.mkdir()
        writer.write_outputs(temp, outcome, maps, writer.build_summary(stages=timer.results(), total_ms=timer.total_ms(), **common))
        check()
    _log_stage(log, "write", timer)

    with timer.stage("verify"):
        state["stage"] = "verify"
        publish.verify(temp, read.rows_received)
        check()
    summary = writer.build_summary(stages=timer.results(), total_ms=timer.total_ms(), **common)
    writer.write_summary(temp, summary)
    _log_stage(log, "verify", timer)

    state["stage"] = "write"
    for w in publish.restrict_permissions(temp):
        log.warning("file permissions cannot be restricted on this system", extra={"stage": "write", "code": w.code})
    run_folder = args.output / run_id
    publish.publish(temp, run_folder)
    for w in outcome.warnings:
        if w.record is None or w.code in STRONG_ROW_WARNINGS:
            where = f"record {w.record}" if w.record is not None else (w.field or "run")
            log.warning(f"{where}", extra={"stage": "clean", "code": w.code})
    dest = summary["destinations"]
    log.info(f"Published {run_folder.name}: received {read.rows_received}, canonical {dest['canonical']}, "
             f"rejected {dest['rejected']}, duplicate losing {dest['duplicate_losing']}",
             extra={"stage": "verify", "code": "-"})
    print(f"Run published: {run_folder}")
    return 0


def _round(value):
    return round(value, 1) if value is not None else None


def _log_stage(log, stage: str, timer: StageTimer) -> None:
    r = timer.results()[stage]
    log.info(f"Stage finished in {r['duration_ms']} ms, peak memory {r['peak_memory_mb']} MB",
             extra={"stage": stage, "code": "-"})
