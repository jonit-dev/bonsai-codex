"""Notes web app: a server-rendered page plus a JSON API, stdlib only."""


def create_app(store_path):
    """Return a configured HTTP server bound to ("127.0.0.1", 0), serving:

    GET /            -> 200 text/html listing the stored notes plus the form below
    GET /api/notes   -> 200 application/json {"notes": [{"id": int, "text": str}, ...]}
    POST /api/notes  -> 201 application/json {"id": int, "text": str} for {"text": "..."};
                        400 {"error": "text is required"} when text is missing or blank
    anything else    -> 404 application/json {"error": "not found"}

    Notes persist as a JSON list in `store_path` and ids increase from 1.
    The page is self-contained: no external CSS, fonts, or scripts.
    """
    raise NotImplementedError("Implement create_app()")
