def model_metadata(model, context_window):
    return {
        "models": [
            {
                "slug": model,
                "display_name": model,
                "base_instructions": "",
                "context_window": context_window,
                "default_verbosity": "low",
                "experimental_supported_tools": [],
                "input_modalities": ["text"],
                "priority": 0,
                "shell_type": "default",
                "support_verbosity": True,
                "supported_in_api": True,
                "supported_reasoning_levels": [],
                "supports_parallel_tool_calls": False,
                "supports_reasoning_summaries": False,
                "truncation_policy": {"limit": 10000, "mode": "bytes"},
                "visibility": "list",
            }
        ]
    }


def cap_positive_int(value, cap):
    if not isinstance(value, int) or value <= 0:
        return cap
    return min(value, cap)



