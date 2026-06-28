import re


def normalize_model_text(text):
    if not isinstance(text, str):
        return text
    text = re.sub(r"<\|channel\>\s*thought\s*", "", text)
    text = re.sub(r"<channel\|>\s*", "", text)
    text = re.sub(r"</?channel>\s*", "", text)
    return text.strip()


def normalize_response_text(data):
    output = data.get("output")
    if not isinstance(output, list):
        return data
    for item in output:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                part["text"] = normalize_model_text(part["text"])
    return data
