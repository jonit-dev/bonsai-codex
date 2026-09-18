from .cli import main
from .http_server import Proxy, read_json, trim_tool_outputs
from .metadata import cap_positive_int, model_metadata
from .patches import (
    add_file_patch,
    apply_patch_command,
    apply_patch_compat_command,
    conditional_apply_patch_command,
    extract_patch_argument,
    is_patch_text,
    normalize_unified_diff_path,
    patch_delimiter,
    patch_file_line,
    repair_add_file_content_lines,
    repair_wrapped_unified_diff,
    sanitize_patch_text,
    shorthand_patch_command,
    unified_add_file_command,
)
from .recovery import (
    force_patch_first_command,
    force_patch_first_missing_tool_command,
    patch_first_is_satisfied,
    payload_contains_successful_patch_output,
    payload_requests_force_patch_first,
    premature_prose_command,
    require_update_patch_after_prior_patch,
)
from .response_translation import (
    extract_embedded_apply_patch,
    extract_embedded_unified_diff,
    missing_apply_patch_payload_command,
    translate_apply_patch_call,
    translate_apply_patch_item,
    translate_apply_patch_objects,
    translate_tool_text_response,
)
from .shell_guard import (
    apply_exec_guard,
    extract_nested_exec_arguments,
    malformed_apply_patch_command,
    rewrite_apply_patch_heredoc_command,
    rewrite_apply_patch_shell_command,
    rewrite_cat_heredoc,
    rewrite_echo_redirect,
    rewrite_shell_write_command,
    rewrite_touch,
    unquote_shell_word,
)
from .streaming import responses_sse, sse_event
from .text import normalize_model_text, normalize_response_text
from .tools import parse_tool_text, tool_denied, tool_name
