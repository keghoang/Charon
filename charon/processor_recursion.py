"""Nuke-bound recursive-run completion transactions for the processor."""

from __future__ import annotations

import time
import traceback
from typing import Any, Callable, Dict


def handle_recursive_completion(
    nuke_module,
    node,
    result_data: Dict[str, Any],
    *,
    update_recursive_inputs: Callable,
    process_next: Callable,
    log_debug: Callable,
    trace_step: Callable,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Advance a recursive run or restore its original Nuke graph on completion."""
    trace_step("mainthread_recursion_enter")
    try:
        is_recursive = bool(node.knob("charon_recursive_enable").value())
        iterations = int(node.knob("charon_recursive_iterations").value())
        current = int(node.knob("charon_recursive_current").value())

        if is_recursive and current < iterations - 1:
            last_output = result_data.get("output_path")
            log_debug(
                f"Recursive Mode: Iteration {current + 1}/{iterations} finished. "
                "Starting next..."
            )
            update_recursive_inputs(node, last_output)
            sleep(2.0)
            process_next()
        elif is_recursive:
            log_debug("Recursive Mode: All iterations completed.")
            try:
                _restore_recursive_graph(nuke_module, node)
                _reset_recursive_attribute(nuke_module, node, log_debug)
                node.knob("charon_recursive_current").setValue(0)
            except Exception as exc:
                log_debug(f"Cleanup failed: {exc}", "ERROR")
    except Exception as exc:
        traceback.print_exc()
        log_debug(f"Recursive trigger failed: {exc}", "WARNING")
        trace_step("mainthread_recursion_error", error=str(exc))
    else:
        trace_step("mainthread_recursion_completed")


def _restore_recursive_graph(nuke_module, node) -> None:
    loop_start = node.knob("charon_recursive_loop_start").value()
    if not loop_start:
        return
    read_node = nuke_module.toNode("Read_Recursive_" + loop_start)
    start_node = nuke_module.toNode(loop_start)
    if not read_node or not start_node:
        return

    final_source_node = read_node
    ivt_node = None
    dependency_flags = nuke_module.INPUTS | nuke_module.HIDDEN_INPUTS
    for dependent in read_node.dependent(dependency_flags, forceEvaluate=True):
        if "InverseViewTransform" in dependent.name():
            ivt_node = dependent
            final_source_node = ivt_node
            break

    restore_candidates = list(read_node.dependent(dependency_flags, forceEvaluate=True))
    if ivt_node:
        restore_candidates.extend(ivt_node.dependent(dependency_flags, forceEvaluate=True))
    for dependent in set(restore_candidates):
        if dependent == ivt_node:
            continue
        _replace_inputs(dependent, (final_source_node, read_node), start_node)
    _replace_inputs(node, (final_source_node, read_node), start_node)

    if ivt_node:
        nuke_module.delete(ivt_node)
    nuke_module.delete(read_node)


def _replace_inputs(node, old_nodes, replacement) -> None:
    for index in range(node.inputs()):
        if node.input(index) in old_nodes:
            node.setInput(index, replacement)


def _reset_recursive_attribute(nuke_module, node, log_debug: Callable) -> None:
    try:
        store_knob = node.knob("charon_recursive_attr_start")
        attribute_start = store_knob.value() if store_knob else None
        if attribute_start is None or attribute_start == "":
            return
        attribute_name = node.knob("charon_recursive_attribute").value()
        if not attribute_name:
            return
        target_knob = None
        if "." in attribute_name:
            node_name, knob_name = attribute_name.split(".", 1)
            target_node = nuke_module.toNode(node_name)
            if target_node and knob_name in target_node.knobs():
                target_knob = target_node[knob_name]
        elif attribute_name in node.knobs():
            target_knob = node[attribute_name]
        if target_knob:
            value = attribute_start
            try:
                value = float(value) if "." in value else int(value)
            except Exception:
                pass
            target_knob.setValue(value)
    except Exception as exc:
        log_debug(f"Failed to reset attribute: {exc}", "WARNING")
