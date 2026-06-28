import json


def sse_event(event, data):
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode("utf-8")


def responses_sse(data):
    chunks = []
    created = dict(data)
    created["status"] = "in_progress"
    chunks.append(sse_event("response.created", {"type": "response.created", "response": created}))
    for index, item in enumerate(data.get("output", [])):
        chunks.append(sse_event("response.output_item.added", {"type": "response.output_item.added", "output_index": index, "item": item}))
        chunks.append(sse_event("response.output_item.done", {"type": "response.output_item.done", "output_index": index, "item": item}))
    chunks.append(sse_event("response.completed", {"type": "response.completed", "response": data}))
    return b"".join(chunks)
