def build_processor_script():
    """Return the PyScript that runs inside the generated CharonOp node."""
    return '''# CharonOp Node Processing Script
import json
import os
import threading
import time
import copy
import uuid

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
        log_debug('Starting CharonOp node processing...')
        node = nuke.thisNode()
        
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
            try:
                node.setMetaData("charon/status_payload", serialized)
            except Exception as metadata_error:
                log_debug(f'Failed to persist status metadata: {metadata_error}', 'WARNING')
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
            try:
                node.setMetaData('charon/last_output', path_value or "")
            except Exception:
                pass

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

        temp_root = temp_root.replace('\\\\', '/')
        temp_dir = os.path.join(temp_root, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

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
            temp_path_nuke = temp_path.replace('\\\\', '/')

            write_node = nuke.createNode('Write', inpanel=False)
            write_node['file'].setValue(temp_path_nuke)
            write_node['file_type'].setValue('png')
            write_node.setInput(0, input_node)
            nuke.execute(write_node, current_frame, current_frame)
            nuke.delete(write_node)

            rendered_files[idx] = temp_path
            log_debug(f\"Rendered '{friendly_name}' to {temp_path_nuke}\")

        charon_panel = None
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
        except Exception:
            app = None
        if not app:
            try:
                from PySide2.QtWidgets import QApplication
                app = QApplication.instance()
            except Exception:
                app = None

        if app:
            for widget in app.topLevelWidgets():
                if hasattr(widget, 'client') and hasattr(widget, 'workflow_data'):
                    charon_panel = widget
                    break
        if not charon_panel or not charon_panel.client:
            log_debug('ComfyUI client not available', 'ERROR')
            raise RuntimeError('ComfyUI client is not available')

        if needs_conversion and not hasattr(charon_panel, 'convert_workflow_on_request'):
            log_debug('Charon panel does not expose conversion helper', 'ERROR')
            raise RuntimeError('Conversion helper is unavailable on the Charon panel')

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
                
                if needs_conversion:
                    update_progress(0.1, 'Converting workflow')
                    try:
                        converted_prompt = charon_panel.convert_workflow_on_request(workflow_data, workflow_path or None)
                    except Exception as exc:
                        log_debug(f'Workflow conversion failed: {exc}', 'ERROR')
                        raise
                    if not is_api_prompt(converted_prompt):
                        raise Exception('Converted workflow is invalid')
                    prompt_data = converted_prompt
                else:
                    prompt_data = workflow_data
                
                update_progress(0.2, 'Uploading images')

                workflow_copy = copy.deepcopy(prompt_data)

                uploaded_assets = {}
                for job in render_jobs:
                    idx = job['index']
                    temp_path = rendered_files.get(idx)
                    mapping = job.get('mapping', {})
                    friendly_name = mapping.get('name', f'Input {idx + 1}') if isinstance(mapping, dict) else f'Input {idx + 1}'
                    if not temp_path or not os.path.exists(temp_path):
                        raise Exception(f\"Temp file missing for '{friendly_name}'\")
                    uploaded_filename = charon_panel.client.upload_image(temp_path)
                    if not uploaded_filename:
                        raise Exception(f\"Failed to upload '{friendly_name}' to ComfyUI\")
                    uploaded_assets[idx] = uploaded_filename
                    log_debug(f\"Uploaded '{friendly_name}' as {uploaded_filename}\")
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
                prompt_id = charon_panel.client.submit_workflow(workflow_copy)
                if not prompt_id:
                    raise Exception('Failed to submit workflow')
                
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
                    if hasattr(charon_panel.client, 'get_progress_for_prompt'):
                        progress_val = charon_panel.client.get_progress_for_prompt(prompt_id)
                        if progress_val > 0:
                            # Map progress from 0.6 to 0.9 during execution
                            mapped_progress = 0.6 + (progress_val * 0.3)
                            update_progress(
                                mapped_progress,
                                f'ComfyUI processing ({progress_val:.1%})',
                                extra={'prompt_id': prompt_id},
                            )
                    
                    history = charon_panel.client.get_history(prompt_id)
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
                                output_path = output_path.replace('\\\\', '/')
                                success = charon_panel.client.download_image(output_filename, output_path)
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

process_charonop_node()'''
