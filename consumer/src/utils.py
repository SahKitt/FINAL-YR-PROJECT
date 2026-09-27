from typing import Dict, Any, List, Union
import logging

logger = logging.getLogger(__name__)

def clean_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively clean a dictionary of callables and private attributes"""
    if not isinstance(d, dict):
        return d
    
    cleaned = {}
    for key, value in d.items():
        if callable(value):
            logger.warning(f"Skipping callable field: {key}")
            continue
        if isinstance(key, str) and key.startswith('_'):
            continue
        
        # Recursively clean nested structures
        if isinstance(value, dict):
            cleaned[key] = clean_dict(value)
        elif isinstance(value, (list, tuple, set)):
            cleaned[key] = clean_list(value)
        else:
            cleaned[key] = value
    
    return cleaned

def clean_list(lst: Union[List, tuple, set]) -> list:
    """Recursively clean a list of callables"""
    if not isinstance(lst, (list, tuple, set)):
        return lst
    
    cleaned = []
    for item in lst:
        if callable(item):
            continue
        if isinstance(item, dict):
            cleaned.append(clean_dict(item))
        elif isinstance(item, (list, tuple, set)):
            cleaned.append(clean_list(item))
        else:
            cleaned.append(item)
    
    return cleaned

def safe_extract_from_pydantic(obj: Any) -> Dict[str, Any]:
    """Safely extract values from Pydantic model without using model_dump"""
    if obj is None:
        return {}
    
    result = {}
    
    # Get all non-private attributes
    for attr_name in dir(obj):
        if attr_name.startswith('_'):
            continue
        
        try:
            attr_value = getattr(obj, attr_name)
            
            if callable(attr_value):
                continue
            
            # Handle nested structures
            if isinstance(attr_value, dict):
                result[attr_name] = clean_dict(attr_value)
            elif isinstance(attr_value, (list, tuple, set)):
                result[attr_name] = clean_list(attr_value)
            else:
                result[attr_name] = attr_value
        except Exception:
            continue
    
    return result