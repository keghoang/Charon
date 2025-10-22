"""
Workflow converter for ComfyUI
Converts non-API workflow format to API format for execution
Created by Seth A. Robinson - https://github.com/SethRobinson/comfyui-workflow-to-api-converter-endpoint
"""

import json
import logging
from typing import Dict, Any, List, Tuple, Optional, Union

# Set up logging
logger = logging.getLogger(__name__)

# Import ComfyUI node information - this is required
try:
    import nodes
except ImportError as e:
    raise ImportError(
        "Cannot import ComfyUI nodes module. "
        "This converter must be run within the ComfyUI environment. "
        "Make sure ComfyUI is properly initialized before using the converter."
    ) from e

# Cache for node definitions
_node_info_cache = {}

def get_node_info_for_type(node_type: str) -> Dict[str, Any]:
    """Get node information for a specific node type"""
    global _node_info_cache
    
    if node_type not in _node_info_cache:
        # Try to get the node info
        if node_type in nodes.NODE_CLASS_MAPPINGS:
            try:
                obj_class = nodes.NODE_CLASS_MAPPINGS[node_type]
                info = {}
                info['input'] = obj_class.INPUT_TYPES()
                info['input_order'] = {key: list(value.keys()) for (key, value) in obj_class.INPUT_TYPES().items()}
                _node_info_cache[node_type] = info
            except Exception as e:
                logger.debug(f"Could not get node info for {node_type}: {e}")
                _node_info_cache[node_type] = None
        else:
            _node_info_cache[node_type] = None
    
    return _node_info_cache.get(node_type)


class WorkflowConverter:
    """Converts non-API workflow format to API prompt format"""
    
    @staticmethod
    def is_api_format(workflow: Dict[str, Any]) -> bool:
        """
        Check if a workflow is already in API format.
        API format has node IDs as keys with 'class_type' and 'inputs'.
        Non-API format has 'nodes', 'links', etc.
        """
        # Check for non-API format indicators
        if 'nodes' in workflow and 'links' in workflow:
            return False
        
        # Check if it looks like API format
        # API format should have numeric string keys with class_type
        for key, value in workflow.items():
            if key in ['prompt', 'extra_data', 'client_id']:
                continue
            if isinstance(value, dict) and 'class_type' in value:
                return True
        
        return False
    
    @staticmethod
    def convert_to_api(workflow: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a non-API workflow to API format.
        
        Args:
            workflow: Non-API format workflow with nodes and links
            
        Returns:
            API format workflow ready for execution
        """
        if WorkflowConverter.is_api_format(workflow):
            # Already in API format
            return workflow
        
        # Extract nodes and links
        workflow_nodes = workflow.get('nodes', [])
        links = workflow.get('links', [])
        
        # Build link map for quick lookup
        # link_id -> (source_node_id, source_slot, target_node_id, target_slot, type)
        link_map = {}
        # Also track which nodes are connected to others (have outputs that go somewhere)
        nodes_with_connected_outputs = set()
        
        for link in links:
            if len(link) >= 6:
                link_id = link[0]
                source_id = link[1]
                source_slot = link[2]
                target_id = link[3]
                target_slot = link[4]
                link_type = link[5] if len(link) > 5 else None
                link_map[link_id] = {
                    'source_id': source_id,
                    'source_slot': source_slot,
                    'target_id': target_id,
                    'target_slot': target_slot,
                    'type': link_type
                }
                # Track that this source node has connected outputs
                nodes_with_connected_outputs.add(source_id)
        
        # First pass: identify PrimitiveNodes and their values
        # Also identify nodes that should be excluded from API format
        primitive_values = {}
        nodes_to_exclude = set()
        bypassed_nodes = set()  # Track bypassed/disabled nodes
        
        for node in workflow_nodes:
            node_id = node.get('id')
            node_type = node.get('type')
            node_mode = node.get('mode', 0)
            
            # Track bypassed/disabled nodes
            if node_mode == 4:
                bypassed_nodes.add(node_id)
            
            # Identify PrimitiveNodes
            if node_type == 'PrimitiveNode':
                # Primitive nodes directly provide values
                value = node.get('widget_value')
                if value is None and node.get('widget'):
                    widget_values = node.get('widgets_values', [])
                    if widget_values:
                        value = widget_values[0]
                
                if value is not None:
                    primitive_values[node_id] = value
                    nodes_to_exclude.add(node_id)
                    continue
                
                # Some primitive nodes store the value in `primitive`
                if 'primitive' in node:
                    primitive_values[node_id] = node['primitive']
                    nodes_to_exclude.add(node_id)
                    continue
            
            # Exclude RerouteNodes (they just pass data through)
            if node_type == 'RerouteNode':
                nodes_to_exclude.add(node_id)
            
            # Exclude nodes that are purely organizational or disabled
            if node_mode == 4:  # Bypassed nodes
                nodes_to_exclude.add(node_id)
        
        # Helper : get link info for a specific input
        def get_link_for_input(node_id: int, input_name: str) -> Optional[Dict[str, Any]]:
            node = next((n for n in workflow_nodes if n.get('id') == node_id), None)
            if not node:
                return None
            
            for input_info in node.get('inputs', []):
                if input_info.get('name') == input_name and input_info.get('link') is not None:
                    link_id = input_info['link']
                    return link_map.get(link_id)
            
            return None
        
        # Helper: create a link representation in API format
        def create_link(target_node_id: int, target_input: str, source_node_id: int, source_slot: str) -> List[Union[str, int]]:
            return [str(source_node_id), source_slot]
        
        # Second pass: build API format
        api_workflow = {}
        
        for node in workflow_nodes:
            node_id = node.get('id')
            node_type = node.get('type')
            
            # Skip nodes that should be excluded
            if node_id in nodes_to_exclude:
                continue
            
            # Skip bypassed nodes
            if node_id in bypassed_nodes:
                continue
            
            # Each node becomes an entry in the API prompt
            api_node = {
                "inputs": {},
                "class_type": node_type,
            }
            
            # Some nodes have custom class names or types that need adjustment
            if node_type == 'KSamplerTeleportNode':
                api_node["class_type"] = 'KSamplerTeleport'
            
            # Copy extra info if available
            if 'properties' in node and node['properties'].get('previousName'):
                api_node.setdefault('_meta', {})['title'] = node['properties']['previousName']
            elif node.get('title'):
                api_node.setdefault('_meta', {})['title'] = node['title']
            
            node_inputs = node.get('inputs', [])
            
            # Keep track of which inputs we've handled (to avoid duplicates)
            handled_inputs = set()
            
            # First process connected inputs
            for input_info in node_inputs:
                input_name = input_info.get('name')
                if not input_name:
                    continue
                
                handled_inputs.add(input_name)
                
                # Check if there's a link (connection)
                link_id = input_info.get('link')
                if link_id is not None:
                    # There's a connection from another node
                    link_info = link_map.get(link_id)
                    if link_info:
                        source_id = link_info['source_id']
                        source_slot = link_info['source_slot'] if link_info.get('source_slot') is not None else 'output'
                        api_node['inputs'][input_name] = create_link(node_id, input_name, source_id, source_slot)
                    continue
                
                # If no link, check if there's a value in widget_values
                widget_values = node.get('widgets_values', [])
                if widget_values:
                    input_names = WorkflowConverter._get_input_names_for_widgets(node)
                    if input_names and len(widget_values) == len(input_names):
                        for idx, widget_value in enumerate(widget_values):
                            if idx < len(input_names):
                                api_node['inputs'][input_names[idx]] = widget_value
                else:
                    # Check if the value comes from a primitive node
                    primitive_map = node.get('inputs', [])
                    for primitive_input in primitive_map:
                        if primitive_input.get('name') == input_name:
                            primitive_id = primitive_input.get('link_node')
                            if primitive_id in primitive_values:
                                api_node['inputs'][input_name] = primitive_values[primitive_id]
                                break
            
            # Process remaining inputs (possibly optional ones)
            node_input_specs = WorkflowConverter._get_input_specs(node_type)
            if node_input_specs:
                for section in ['required', 'optional']:
                    if section in node_input_specs:
                        for input_name, input_spec in node_input_specs[section].items():
                            if input_name in handled_inputs:
                                continue
                            
                            if isinstance(input_spec, tuple) and len(input_spec) >= 1:
                                # This is a regular input
                                input_type = input_spec[0]
                                default_value = input_spec[1] if len(input_spec) > 1 else None
                                
                                # Check for connection first
                                link_info = get_link_for_input(node_id, input_name)
                                if link_info:
                                    source_id = link_info['source_id']
                                    source_slot = link_info['source_slot'] if link_info.get('source_slot') is not None else 'output'
                                    api_node['inputs'][input_name] = create_link(node_id, input_name, source_id, source_slot)
                                    continue
                                
                                # Check if there's a primitive value
                                if 'inputs' in node:
                                    for primitive_input in node['inputs']:
                                        if primitive_input.get('name') == input_name and primitive_input.get('link_node') in primitive_values:
                                            api_node['inputs'][input_name] = primitive_values[primitive_input['link_node']]
                                            break
                                    else:
                                        # No primitive value found, use default if available
                                        if default_value is not None:
                                            api_node['inputs'][input_name] = default_value
                                else:
                                    if default_value is not None:
                                        api_node['inputs'][input_name] = default_value
                            else:
                                # Complex input spec (like a selection with options) - use default if available
                                if isinstance(input_spec, dict) and 'default' in input_spec:
                                    api_node['inputs'][input_name] = input_spec['default']
            
            api_workflow[str(node_id)] = api_node
        
        # Include prompt extras if available
        if 'prompt' in workflow:
            api_workflow['prompt'] = workflow['prompt']
        if 'extra_data' in workflow:
            api_workflow['extra_data'] = workflow['extra_data']
        if 'client_id' in workflow:
            api_workflow['client_id'] = workflow['client_id']
        
        return api_workflow

    @staticmethod
    def _get_input_specs(node_type: str) -> Optional[Dict[str, Any]]:
        """
        Get input specifications for a node type using node metadata.
        """
        node_info = get_node_info_for_type(node_type)
        
        if node_info and 'input' in node_info:
            return node_info['input']
        
        return None

    @staticmethod
    def _get_input_names_for_widgets(node: Dict[str, Any]) -> Optional[List[str]]:
        """
        Get input names that correspond to widget values for a node.
        """
        node_type = node.get('type')
        if not node_type:
            return None
        
        node_info = get_node_info_for_type(node_type)
        if node_info and 'input_order' in node_info:
            input_order = node_info['input_order']
            if 'required' in input_order:
                return input_order['required']
        
        return None

# Helper functions for flattening Set/Get nodes

def flatten_set_get_nodes(ui_workflow: Dict[str, Any], api_workflow: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten Set/Get node pairs in the API workflow by replacing Get nodes with direct links to Set sources.
    """
    set_nodes = {}
    get_nodes = {}
    
    # Find SetNode and GetNode pairs
    for node in ui_workflow.get('nodes', []):
        node_id = node.get('id')
        node_type = node.get('type')
        
        if node_type == 'SetNode':
            # Get the name from widgets or properties
            name = None
            if node.get('title'):
                name = node['title']
            elif node.get('properties', {}).get('previousName'):
                name = node['properties']['previousName']
            elif node.get('widgets_values'):
                name = node['widgets_values'][0]
            
            if name:
                set_nodes[name] = node_id
        
        elif node_type == 'GetNode':
            # Get the name similarly
            name = None
            if node.get('title'):
                name = node['title']
            elif node.get('properties', {}).get('previousName'):
                name = node['properties']['previousName']
            elif node.get('widgets_values'):
                name = node['widgets_values'][0]
            
            if name:
                get_nodes[name] = node_id
    
    if not set_nodes or not get_nodes:
        return api_workflow
    
    # Create a copy to modify
    updated_workflow = dict(api_workflow)
    
    # Find links that go through GetNodes and replace them
    for name, get_node_id in get_nodes.items():
        set_node_id = set_nodes.get(name)
        if set_node_id is None:
            continue
        
        get_node_key = str(get_node_id)
        set_node_key = str(set_node_id)
        
        if get_node_key not in updated_workflow or set_node_key not in updated_workflow:
            continue
        
        # Find the output slot of the SetNode (usually "value" or first output)
        set_node = updated_workflow[set_node_key]
        set_outputs = set_node.get('outputs', {})
        
        source_slot = None
        if set_outputs:
            source_slot = next(iter(set_outputs))
        else:
            source_slot = 'value'
        
        # Replace all references to the GetNode with the SetNode
        for node_id, node_data in updated_workflow.items():
            if not isinstance(node_data, dict) or node_id == set_node_key:
                continue
            
            inputs = node_data.get('inputs', {})
            if not isinstance(inputs, dict):
                continue
            
            for input_name, input_value in list(inputs.items()):
                if isinstance(input_value, list) and len(input_value) == 2:
                    link_node_id, link_slot = input_value
                    if str(link_node_id) == get_node_key:
                        inputs[input_name] = [set_node_key, source_slot]
        
        # Remove the GetNode from the prompt
        updated_workflow.pop(get_node_key, None)
    
    return updated_workflow
