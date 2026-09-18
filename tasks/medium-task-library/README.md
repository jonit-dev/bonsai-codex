# Medium Benchmark: Task Library

Implement the `tasklib` package using only the Python standard library.

Requirements:

- `TaskService.add_task(title, priority="normal", tags=None)` creates tasks with incrementing integer IDs.
- Titles must be non-empty after trimming whitespace.
- Priority must be one of `low`, `normal`, or `high`.
- Tags are normalized to lowercase, stripped, deduplicated, and sorted.
- `TaskService.complete_task(task_id)` marks an existing task complete and raises `KeyError` for unknown IDs.
- `TaskService.list_tasks(status=None, tag=None)` supports `open`, `completed`, and tag filtering.
- `TaskRepository` stores tasks in JSON and reloads existing data.

Verify with:

```sh
python3 -m unittest discover -s tests -v
```
