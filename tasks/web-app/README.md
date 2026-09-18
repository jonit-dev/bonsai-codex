# Task: notes web app (server-rendered page + JSON API)

Implement `create_app(store_path)` in `app.py` with the Python standard library only. The
contract and the routes are in the `app.py` docstring; `tests/test_app.py` is the spec.

Verify with:

```sh
python3 -m unittest discover -s tests -v
```

Run it by hand:

```sh
python3 -c "import app, threading; s = app.create_app('/tmp/notes.json'); s.serve_forever()"
# then open http://127.0.0.1:<port printed by server_address>
```
