# CharonOp Node Processing Script
import copy
import json
import os
import threading
import time
import uuid
from typing import Optional, Tuple

from .conversion_cache import (
    compute_workflow_hash,
    desired_prompt_path,
    load_cached_conversion,
    write_conversion_cache,
)
from .paths import get_default_comfy_launch_path
from .workflow_runtime import convert_workflow as runtime_convert_workflow
from . import preferences


def _get_qt_application():
    """Return the active Qt application instance if available."""
    try:
        from PySide6.QtWidgets import QApplication  # type: ignore
    except ImportError:
        try:
            from PySide2.QtWidgets import QApplication  # type: ignore
        except ImportError:
            return None
    return QApplication.instance()


def _find_charon_window():
    """Locate the active Galt/Charon window to access Comfy context."""
    app = _get_qt_application()
    if not app:
        return None

    for widget in app.topLevelWidgets():
        if getattr(widget, "_charon_is_galt_window", False):
            return widget

    for widget in app.topLevelWidgets():
        if hasattr(widget, "comfy_client"):
            return widget

    return None


def _read_comfy_preferences_path() -> Optional[str]:
    prefs = preferences.load_preferences()
    path = prefs.get("comfyui_launch_path")
    if isinstance(path, str):
        path = path.strip()
        if path:
            return path
    elif isinstance(path, (list, tuple)):
        # Defensive: handle legacy structures accidentally persisted
        flattened = "".join(str(part) for part in path if part)
        if flattened:
            return flattened
    return None


def _resolve_comfy_environment() -> Tuple[Optional[object], Optional[object], Optional[str]]:
    """
    Return (window, client, comfy_path) from the active prototype UI context.
    """
    window = _find_charon_window()
    client = getattr(window, "comfy_client", None) if window else None

    if client is None and window is not None:
        connection = getattr(window, "comfy_connection_widget", None)
        if connection is not None:
            getter = getattr(connection, "current_client", None)
            if callable(getter):
                try:
                    client = getter()
                except Exception:
                    client = None
            if client is None:
                property_value = getattr(connection, "client", None)
                if property_value is not None and not callable(property_value):
                    client = property_value
            if client is None and hasattr(connection, "_client"):
                client = getattr(connection, "_client", None)

    comfy_path = None
    if window is not None:
        connection = getattr(window, "comfy_connection_widget", None)
        if connection is not None:
            path_attr = getattr(connection, "current_comfy_path", None)
            if callable(path_attr):
                try:
                    comfy_path = path_attr()
                except Exception:
                    comfy_path = None
            elif isinstance(path_attr, str):
                comfy_path = path_attr
            elif hasattr(connection, "_comfy_path"):
                comfy_path = getattr(connection, "_comfy_path", None)

    if not comfy_path:
        comfy_path = _read_comfy_preferences_path()

    if not comfy_path:
        default_path = get_default_comfy_launch_path()
        if default_path and os.path.exists(default_path):
            comfy_path = default_path

    return window, client, comfy_path


def is_api_prompt(data):
    if not isinstance(data, dict):
        return False
    if not data:
        return False
    for value in data.values():
        if not isinstance(value, dict) or 'class_type' not in value:
            return False
    return True

def normalize_identifier(value):
    if value is None:
        return ''
    text = str(value).strip()
    lowered = text.lower()
    if lowered.startswith('set_'):
        text = text[4:]
    elif lowered.startswith('get_'):
        text = text[4:]
    return text.lower()

def extract_ui_identifier(node):
    title = str(node.get('title') or '').strip()
    if title:
        return title
    widgets = node.get('widgets_values', [])
    if widgets:
        return str(widgets[0])
    properties = node.get('properties', {})
    if isinstance(properties, dict):
        prev = properties.get('previousName')
        if prev:
            return str(prev)
    return ''

def build_set_targets(ui_workflow):
    targets = {}
    if not isinstance(ui_workflow, dict):
        return targets
    links = ui_workflow.get('links', [])
    link_lookup = {}
    for link in links:
        if isinstance(link, list) and len(link) >= 3:
            link_lookup[link[0]] = (str(link[1]), link[2])
    for node in ui_workflow.get('nodes', []):
        if not isinstance(node, dict):
            continue
        if node.get('type') != 'SetNode':
            continue
        identifier = extract_ui_identifier(node)
        if not identifier:
            continue
        normalized = normalize_identifier(identifier)
        for input_slot in node.get('inputs', []):
            link_id = input_slot.get('link')
            if link_id in link_lookup:
                targets[normalized] = link_lookup[link_id]
                break
    return targets

def log_debug(message, level='INFO'):
    timestamp = time.strftime('%H:%M:%S')
    print(f'[{timestamp}] [CHARONOP] [{level}] {message}')

def process_charonop_node():
    try:
        import nuke  # type: ignore
    except ImportError as exc:  # pragma: no cover - guarded for testing
        raise RuntimeError('Nuke is required to process CharonOp nodes.') from exc

    try:
        log_debug('Starting CharonOp node processing...')
        node = nuke.thisNode()

        if hasattr(node, 'setMetaData'):
            metadata_writer = node.setMetaData
        elif hasattr(node, 'setMetadata'):
            metadata_writer = node.setMetadata
        else:
            metadata_writer = None

        metadata_warning_emitted = False

        def write_metadata(key, value):
            nonlocal metadata_warning_emitted
            if not metadata_writer:
                if not metadata_warning_emitted:
                    log_debug('Metadata persistence unavailable on this node; falling back to knob storage.', 'WARNING')
                    metadata_warning_emitted = True
                return False
            try:
                metadata_writer(key, value)
                return True
            except Exception as exc:
                if not metadata_warning_emitted:
                    log_debug(f"Failed to persist metadata '{key}': {exc}", 'WARNING')
                    metadata_warning_emitted = True
                return False
        
        # Set initial status
        try:
            node.knob('charon_status').setValue('Preparing node')
            node.knob('charon_progress').setValue(0.0)
        except Exception:
            pass

        try:
            status_payload_knob = node.knob('charon_status_payload')
        except Exception:
            status_payload_knob = None

        def resolve_auto_import():
            try:
                knob = node.knob('charon_auto_import')
                if knob is not None:
                    try:
                        return bool(int(knob.value()))
                    except Exception:
                        return bool(knob.value())
            except Exception:
                pass
            try:
                meta = node.metadata('charon/auto_import')
                if isinstance(meta, str):
                    lowered = meta.strip().lower()
                    if lowered in {'0', 'false', 'off', 'no'}:
                        return False
                    if lowered in {'1', 'true', 'on', 'yes'}:
                        return True
                elif meta is not None:
                    return bool(meta)
            except Exception:
                pass
            return True

        current_run_id = str(uuid.uuid4())
        run_started_at = time.time()

        def load_status_payload():
            raw = None
            try:
                raw = node.metadata("charon/status_payload")
            except Exception:
                pass
            if not raw and status_payload_knob:
                try:
                    raw = status_payload_knob.value()
                except Exception:
                    raw = None
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except Exception:
                return {}

        def save_status_payload(payload):
            serialized = json.dumps(payload)
            write_metadata("charon/status_payload", serialized)
            if status_payload_knob:
                try:
                    status_payload_knob.setValue(serialized)
                except Exception as payload_error:
                    log_debug(f'Failed to store status payload knob: {payload_error}', 'WARNING')

        def ensure_history(payload):
            runs = payload.get('runs')
            if not isinstance(runs, list):
                runs = []
            payload['runs'] = runs
            return runs

        def update_last_output(path_value):
            try:
                knob = node.knob('charon_last_output')
                if knob is not None:
                    knob.setValue(path_value or "")
            except Exception:
                pass
            write_metadata('charon/last_output', path_value or "")

        def initialize_status(message='Initializing'):
            payload = load_status_payload()
            runs = ensure_history(payload)
            now = run_started_at
            auto_flag = resolve_auto_import()
            payload['current_run'] = {
                'id': current_run_id,
                'status': 'Processing',
                'message': message,
                'progress': 0.0,
                'started_at': now,
                'updated_at': now,
                'auto_import': auto_flag,
            }
            payload.update({
                'status': message,
                'state': 'Processing',
                'message': message,
                'progress': 0.0,
                'run_id': current_run_id,
                'started_at': now,
                'updated_at': now,
                'auto_import': auto_flag,
            })
            payload['runs'] = runs
            save_status_payload(payload)

        initialize_status('Preparing node')

        workflow_data_str = node.knob('workflow_data').value()
        input_mapping_str = node.knob('input_mapping').value()
        temp_root = node.knob('charon_temp_dir').value()
        try:
            workflow_path = node.knob('workflow_path').value()
        except Exception:
            workflow_path = ''

        if not workflow_data_str or not input_mapping_str:
            log_debug('No workflow data found on CharonOp node', 'ERROR')
            raise RuntimeError('Missing workflow data on CharonOp node')

        workflow_data = json.loads(workflow_data_str)
        input_mapping = json.loads(input_mapping_str)
        needs_conversion = not is_api_prompt(workflow_data)
        set_targets = build_set_targets(workflow_data) if needs_conversion else {}

        if not temp_root:
            log_debug('Temp directory not configured', 'ERROR')
            raise RuntimeError('Charon temp directory is not configured')

        temp_root = temp_root.replace('\\', '/')
        temp_dir = os.path.join(temp_root, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        converted_prompt_path = None
        workflow_folder = ''
        candidate_paths = [workflow_path]
        try:
            meta_path = node.metadata('charon/workflow_path')
            if meta_path and meta_path not in candidate_paths:
                candidate_paths.append(meta_path)
        except Exception:
            pass

        for candidate in candidate_paths:
            if not candidate:
                continue
            folder_candidate = candidate if os.path.isdir(candidate) else os.path.dirname(candidate)
            if folder_candidate and os.path.isdir(folder_candidate):
                workflow_folder = folder_candidate
                break

        connected_inputs = {}
        total_inputs = node.inputs()
        for index in range(total_inputs):
            input_node = node.input(index)
            if input_node is not None:
                connected_inputs[index] = input_node

        if not connected_inputs:
            log_debug('Please connect at least one input node', 'ERROR')
            raise RuntimeError('Please connect at least one input node before processing')

        render_jobs = []
        if isinstance(input_mapping, list):
            for mapping in input_mapping:
                if not isinstance(mapping, dict):
                    continue
                index = mapping.get('index')
                if index is None or index not in connected_inputs:
                    continue
                render_jobs.append({
                    'index': index,
                    'mapping': mapping,
                    'node': connected_inputs[index]
                })

        if not render_jobs:
            first_index, first_node = next(iter(connected_inputs.items()))
            render_jobs.append({
                'index': first_index,
                'mapping': {'name': f'Input {first_index + 1}', 'type': 'image'},
                'node': first_node
            })

        primary_job = None
        for job in render_jobs:
            mapping = job.get('mapping', {})
            if isinstance(mapping, dict) and mapping.get('type') == 'image':
                primary_job = job
                break
        if not primary_job:
            primary_job = render_jobs[0]
        primary_index = primary_job['index']

        rendered_files = {}
        current_frame = int(nuke.frame())
        for job in render_jobs:
            idx = job['index']
            mapping = job.get('mapping', {})
            input_node = job['node']
            friendly_name = mapping.get('name', f'Input {idx + 1}') if isinstance(mapping, dict) else f'Input {idx + 1}'
            safe_tag = ''.join(c if c.isalnum() else '_' for c in friendly_name).strip('_') or f'input_{idx + 1}'
            temp_path = os.path.join(temp_dir, f'charon_{safe_tag}_{str(uuid.uuid4())[:8]}.png')
            temp_path_nuke = temp_path.replace('\\', '/')

            write_node = nuke.createNode('Write', inpanel=False)
            write_node['file'].setValue(temp_path_nuke)
            write_node['file_type'].setValue('png')
            write_node.setInput(0, input_node)
            nuke.execute(write_node, current_frame, current_frame)
            nuke.delete(write_node)

            rendered_files[idx] = temp_path
            log_debug(f"Rendered '{friendly_name}' to {temp_path_nuke}")

        _charon_window, comfy_client, comfy_path = _resolve_comfy_environment()
        if not comfy_client:
            log_debug('ComfyUI client not available', 'ERROR')
            raise RuntimeError('ComfyUI client is not available')

        results_dir = os.path.join(temp_root, 'results')
        os.makedirs(results_dir, exist_ok=True)
        result_file = os.path.join(results_dir, f"charon_result_{int(time.time())}.json")

        def update_progress(progress, status='Processing', error=None, extra=None):
            try:
                node.knob('charon_progress').setValue(progress)
                node.knob('charon_status').setValue(status)
            except Exception:
                pass

            lifecycle = 'Processing'
            normalized = (status or '').lower()
            if progress < 0 or normalized.startswith('error'):
                lifecycle = 'Error'
            elif progress >= 1.0:
                lifecycle = 'Completed'

            payload = load_status_payload()
            runs = ensure_history(payload)
            current_run = payload.get('current_run')
            if not isinstance(current_run, dict) or current_run.get('id') != current_run_id:
                current_run = {
                    'id': current_run_id,
                    'started_at': run_started_at,
                }
            now = time.time()
            auto_import_flag = resolve_auto_import()
            current_run.update({
                'status': lifecycle,
                'message': status,
                'progress': progress,
                'updated_at': now,
                'auto_import': auto_import_flag,
            })
            if extra and isinstance(extra, dict):
                current_run.update(extra)
                if 'output_path' in extra:
                    update_last_output(extra.get('output_path'))
            if lifecycle == 'Completed':
                current_run['completed_at'] = now
            if error:
                current_run['error'] = error

            payload.update({
                'status': status,
                'state': lifecycle,
                'message': status,
                'progress': progress,
                'run_id': current_run_id,
                'updated_at': now,
                'current_run': current_run,
                'auto_import': auto_import_flag,
            })
            if extra and isinstance(extra, dict):
                payload.update(extra)
            if error:
                payload['last_error'] = error

            if lifecycle in ('Completed', 'Error'):
                if lifecycle == 'Error':
                    update_last_output(None)
                summary = {
                    'id': current_run_id,
                    'status': lifecycle,
                    'message': status,
                    'progress': progress,
                    'started_at': current_run.get('started_at', run_started_at),
                    'completed_at': current_run.get('completed_at', now),
                    'error': current_run.get('error'),
                    'auto_import': auto_import_flag,
                }
                for key in ('output_path', 'elapsed_time', 'prompt_id'):
                    if key in current_run:
                        summary[key] = current_run[key]
                runs.append(summary)
                payload['runs'] = runs[-10:]
                payload.pop('current_run', None)
            else:
                payload['runs'] = runs
                payload['current_run'] = current_run

            save_status_payload(payload)

            log_debug(f'Updated progress: {progress:.1%} - {status}')

        def background_process():
            try:
                update_progress(0.05, 'Starting processing')
                conversion_extra = {}
                workflow_hash = compute_workflow_hash(workflow_data) if needs_conversion else None
                cache_hit = None

                if needs_conversion and workflow_hash and workflow_folder:
                    try:
                        cache_hit = load_cached_conversion(workflow_folder, workflow_hash)
                    except Exception as exc:
                        log_debug(f'Conversion cache read failed: {exc}', 'WARNING')
                        cache_hit = None

                prompt_data = workflow_data

                if needs_conversion:
                    if cache_hit:
                        try:
                            with open(cache_hit['prompt_path'], 'r', encoding='utf-8') as handle:
                                prompt_data = json.load(handle)
                            converted_prompt_path = cache_hit['prompt_path'].replace('\\', '/')
                            conversion_extra.update({
                                'converted_prompt_path': converted_prompt_path,
                                'conversion_cached': True,
                            })
                            update_progress(0.1, 'Using cached conversion', extra=conversion_extra)
                        except Exception as exc:
                            log_debug(f'Failed to read cached conversion: {exc}', 'WARNING')
                            cache_hit = None
                            converted_prompt_path = None

                    if not cache_hit:
                        update_progress(0.1, 'Converting workflow')
                        if not comfy_path:
                            raise RuntimeError(
                                'ComfyUI path is not configured. Open the prototype and set the launch path.'
                            )
                        try:
                            converted_prompt = runtime_convert_workflow(workflow_data, comfy_path)
                        except Exception as exc:
                            log_debug(f'Workflow conversion failed: {exc}', 'ERROR')
                            raise
                        if not is_api_prompt(converted_prompt):
                            raise Exception('Converted workflow is invalid')
                        prompt_data = converted_prompt

                        if workflow_hash and workflow_folder:
                            try:
                                target_path = desired_prompt_path(workflow_folder, workflow_path or '', workflow_hash)
                                target_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(target_path, 'w', encoding='utf-8') as handle:
                                    json.dump(converted_prompt, handle, indent=2)
                                stored_path = write_conversion_cache(
                                    workflow_folder,
                                    workflow_path or '',
                                    workflow_hash,
                                    str(target_path),
                                )
                                converted_prompt_path = stored_path.replace('\\', '/')
                            except Exception as exc:
                                log_debug(f'Failed to cache converted workflow: {exc}', 'WARNING')
                                debug_dir = os.path.join(temp_root, 'debug')
                                os.makedirs(debug_dir, exist_ok=True)
                                fallback_path = os.path.join(
                                    debug_dir,
                                    f'converted_{current_run_id}.json',
                                )
                                with open(fallback_path, 'w', encoding='utf-8') as handle:
                                    json.dump(converted_prompt, handle, indent=2)
                                converted_prompt_path = fallback_path.replace('\\', '/')
                        else:
                            debug_dir = os.path.join(temp_root, 'debug')
                            os.makedirs(debug_dir, exist_ok=True)
                            fallback_path = os.path.join(
                                debug_dir,
                                f'converted_{current_run_id}.json',
                            )
                            with open(fallback_path, 'w', encoding='utf-8') as handle:
                                json.dump(converted_prompt, handle, indent=2)
                            converted_prompt_path = fallback_path.replace('\\', '/')

                        conversion_extra.update({
                            'converted_prompt_path': converted_prompt_path,
                            'conversion_cached': False,
                        })

                update_progress(0.2, 'Uploading images', extra=conversion_extra or None)

                workflow_copy = copy.deepcopy(prompt_data)

                uploaded_assets = {}
                for job in render_jobs:
                    idx = job['index']
                    temp_path = rendered_files.get(idx)
                    mapping = job.get('mapping', {})
                    friendly_name = mapping.get('name', f'Input {idx + 1}') if isinstance(mapping, dict) else f'Input {idx + 1}'
                    if not temp_path or not os.path.exists(temp_path):
                        raise Exception(f"Temp file missing for '{friendly_name}'")
                    uploaded_filename = comfy_client.upload_image(temp_path)
                    if not uploaded_filename:
                        raise Exception(f"Failed to upload '{friendly_name}' to ComfyUI")
                    uploaded_assets[idx] = uploaded_filename
                    log_debug(f"Uploaded '{friendly_name}' as {uploaded_filename}")
                    progress = 0.2 + (0.2 * (len(uploaded_assets) / len(render_jobs)))
                    update_progress(progress, f'Uploaded {len(uploaded_assets)}/{len(render_jobs)} images')

                def assign_to_node(target_node_id, filename, target_socket=None):
                    node_key = str(target_node_id)
                    node_entry = workflow_copy.get(node_key)
                    if not isinstance(node_entry, dict):
                        return
                    inputs_dict = node_entry.setdefault('inputs', {})
                    if not isinstance(inputs_dict, dict):
                        return
                    if target_socket and target_socket in inputs_dict:
                        inputs_dict[target_socket] = filename
                        return
                    if 'image' in inputs_dict and not isinstance(inputs_dict.get('image'), list):
                        inputs_dict['image'] = filename
                    elif 'input' in inputs_dict and not isinstance(inputs_dict.get('input'), list):
                        inputs_dict['input'] = filename
                    elif 'mask' in inputs_dict and not isinstance(inputs_dict.get('mask'), list):
                        inputs_dict['mask'] = filename
                    else:
                        inputs_dict['image'] = filename

                if isinstance(input_mapping, list):
                    for job in render_jobs:
                        mapping = job.get('mapping', {})
                        idx = job['index']
                        uploaded_filename = uploaded_assets.get(idx)
                        if not uploaded_filename:
                            continue
                        node_id = mapping.get('node_id')
                        source = mapping.get('source')
                        if source == 'set_node':
                            identifier = mapping.get('identifier')
                            normalized = normalize_identifier(identifier)
                            target = set_targets.get(normalized)
                            if target:
                                assign_to_node(target[0], uploaded_filename)
                                continue
                            if node_id is not None:
                                set_entry = workflow_copy.get(str(node_id))
                                if isinstance(set_entry, dict):
                                    for value in set_entry.get('inputs', {}).values():
                                        if isinstance(value, list) and len(value) >= 1:
                                            assign_to_node(value[0], uploaded_filename)
                        elif node_id is not None:
                            assign_to_node(node_id, uploaded_filename)
                        else:
                            for target_id, target_data in workflow_copy.items():
                                if isinstance(target_data, dict) and target_data.get('class_type') == 'LoadImage':
                                    assign_to_node(target_id, uploaded_filename)
                                    break
                else:
                    filename = uploaded_assets.get(primary_index)
                    if filename:
                        for target_id, target_data in workflow_copy.items():
                            if isinstance(target_data, dict) and target_data.get('class_type') == 'LoadImage':
                                assign_to_node(target_id, filename)
                                break

                update_progress(0.5, 'Submitting workflow')
                prompt_id = comfy_client.submit_workflow(workflow_copy)
                if not prompt_id:
                    save_hint = ''
                    if converted_prompt_path:
                        save_hint = f' (converted prompt saved to {converted_prompt_path})'
                    log_debug(f'ComfyUI did not return a prompt id{save_hint}', 'ERROR')
                    raise Exception(f'Failed to submit workflow{save_hint}')
                
                node.knob('charon_prompt_id').setValue(prompt_id)

                start_time = time.time()
                timeout = 300
                update_progress(
                    0.6,
                    'Processing on ComfyUI',
                    extra={
                        'prompt_id': prompt_id,
                        'prompt_submitted_at': start_time,
                    },
                )
                
                while time.time() - start_time < timeout:
                    # Check progress via queue status
                    if hasattr(comfy_client, 'get_progress_for_prompt'):
                        progress_val = comfy_client.get_progress_for_prompt(prompt_id)
                        if progress_val > 0:
                            # Map progress from 0.6 to 0.9 during execution
                            mapped_progress = 0.6 + (progress_val * 0.3)
                            update_progress(
                                mapped_progress,
                                f'ComfyUI processing ({progress_val:.1%})',
                                extra={'prompt_id': prompt_id},
                            )
                    
                    history = comfy_client.get_history(prompt_id)
                    if history and prompt_id in history:
                        history_data = history[prompt_id]
                        status_str = history_data.get('status', {}).get('status_str')
                        if status_str == 'success':
                            outputs = history_data.get('outputs', {})
                            if outputs:
                                output_filename = None
                                for node_id, node_data in workflow_copy.items():
                                    if node_data.get('class_type') == 'SaveImage' and node_id in outputs:
                                        images = outputs[node_id].get('images', [])
                                        if images:
                                            output_filename = images[0].get('filename')
                                            break
                                if not output_filename:
                                    raise Exception('ComfyUI did not return an output filename')
                                update_progress(
                                    0.95,
                                    'Downloading result',
                                    extra={'prompt_id': prompt_id},
                                )
                                output_dir = os.path.join(temp_root, 'results')
                                os.makedirs(output_dir, exist_ok=True)
                                output_path = os.path.join(output_dir, f'comfyui_result_{int(time.time())}.png')
                                output_path = output_path.replace('\\', '/')
                                success = comfy_client.download_image(output_filename, output_path)
                                if not success:
                                    raise Exception('Failed to download result image from ComfyUI')
                                elapsed = time.time() - start_time
                                update_progress(
                                    1.0,
                                    'Completed',
                                    extra={
                                        'output_path': output_path,
                                        'elapsed_time': elapsed,
                                    },
                                )
                                result_data = {
                                    'success': True,
                                    'output_path': output_path,
                                    'node_x': node.xpos(),
                                    'node_y': node.ypos(),
                                    'elapsed_time': elapsed
                                }
                                with open(result_file, 'w') as fp:
                                    json.dump(result_data, fp)
                                return
                        elif status_str == 'error':
                            error_msg = history_data.get('status', {}).get('status_message', 'Unknown error')
                            raise Exception(f'ComfyUI failed: {error_msg}')
                    time.sleep(1.0)
                raise Exception('Processing timed out')

            except Exception as exc:
                message = f'Error: {exc}'
                update_progress(-1.0, message, error=str(exc))
                result_data = {
                    'success': False,
                    'error': str(exc),
                    'node_x': node.xpos(),
                    'node_y': node.ypos()
                }
                with open(result_file, 'w') as fp:
                    json.dump(result_data, fp)

        bg_thread = threading.Thread(target=background_process)
        bg_thread.daemon = True
        bg_thread.start()

        def result_watcher():
            for _ in range(300):
                if os.path.exists(result_file):
                    try:
                        with open(result_file, 'r') as fp:
                            result_data = json.load(fp)
                        if result_data.get('success'):
                            elapsed = result_data.get('elapsed_time', 0)

                            def cleanup_files():
                                try:
                                    if os.path.exists(result_file):
                                        os.remove(result_file)
                                except Exception as cleanup_error:
                                    log_debug(f'Could not remove result file: {cleanup_error}', 'WARNING')
                                try:
                                    for temp_path in list(rendered_files.values()):
                                        if os.path.exists(temp_path):
                                            os.remove(temp_path)
                                            log_debug(f'Cleaned up temp file: {temp_path}')
                                except Exception as cleanup_error:
                                    log_debug(f'Could not clean up files: {cleanup_error}', 'WARNING')

                            if resolve_auto_import():
                                def create_read_node():
                                    try:
                                        read_node = nuke.createNode('Read')
                                        read_node['file'].setValue(result_data['output_path'])
                                        read_node.setXpos(result_data['node_x'] + 200)
                                        read_node.setYpos(result_data['node_y'])
                                        read_node.setSelected(True)
                                        log_debug(f'Success! Completed in {elapsed:.1f}s. Read node created.')
                                        log_debug(f'Output file located at: {result_data["output_path"]}')
                                    except Exception as exc:
                                        log_debug(f'Error creating Read node: {exc}', 'ERROR')
                                    finally:
                                        cleanup_files()
                                nuke.executeInMainThread(create_read_node)
                            else:
                                log_debug('Auto import disabled; skipping Read node creation.')
                                log_debug(f'Output file located at: {result_data["output_path"]}')
                                cleanup_files()
                        else:
                            error_msg = result_data.get('error', 'Unknown error')
                            log_debug(f'Processing failed: {error_msg}', 'ERROR')
                            try:
                                for temp_path in list(rendered_files.values()):
                                    if os.path.exists(temp_path):
                                        os.remove(temp_path)
                                        log_debug(f'Cleaned up temp file: {temp_path}')
                            except Exception as cleanup_error:
                                log_debug(f'Could not clean up files after failure: {cleanup_error}', 'WARNING')
                    except Exception as exc:
                        log_debug(f'Error reading result: {exc}', 'ERROR')
                    break
                time.sleep(1.0)

        watcher_thread = threading.Thread(target=result_watcher)
        watcher_thread.daemon = True
        watcher_thread.start()

        log_debug('Processing started in background')

    except Exception as exc:
        log_debug(f'Error: {exc}', 'ERROR')
        message = f'Error: {exc}'
        try:
            node.knob('charon_status').setValue(message)
            node.knob('charon_progress').setValue(-1.0)
        except Exception:
            pass
        if 'load_status_payload' in locals() and 'save_status_payload' in locals():
            try:
                payload = load_status_payload()
                runs = ensure_history(payload) if 'ensure_history' in locals() else payload.setdefault('runs', [])
                now = time.time()
                payload.update({
                    'status': message,
                    'state': 'Error',
                    'message': message,
                    'progress': -1.0,
                    'run_id': locals().get('current_run_id'),
                    'updated_at': now,
                    'last_error': str(exc),
                })
                runs.append({
                    'id': locals().get('current_run_id'),
                    'status': 'Error',
                    'message': message,
                    'progress': -1.0,
                    'started_at': locals().get('run_started_at'),
                    'completed_at': now,
                    'error': str(exc),
                })
                payload['runs'] = runs[-10:] if isinstance(runs, list) else runs
                payload.pop('current_run', None)
                save_status_payload(payload)
            except Exception as payload_error:
                log_debug(f'Failed to persist error payload: {payload_error}', 'WARNING')
