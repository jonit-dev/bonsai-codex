# Task: tiny API (single file)

Implement `create_app()` in `api.py` with the Python standard library only. It returns a
configured HTTP server bound to `("127.0.0.1", 0)`; `tests/test_api.py` is the spec.

Behaviour: `GET /health` -> `200 {"status":"ok"}`; `POST /items {"name":"alpha"}` ->
`201 {"id":1,"name":"alpha"}`; `GET /items` -> `200 {"items":[...]}`; a missing or blank
name -> `400 {"error":"name is required"}`; unknown routes -> `404 {"error":"not found"}`.

Verify with:

```sh
python3 -m unittest discover -s tests -v
```
