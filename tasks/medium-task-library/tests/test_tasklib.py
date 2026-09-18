import tempfile
import unittest
from pathlib import Path

from tasklib import TaskRepository, TaskService


class TaskServiceTests(unittest.TestCase):
    def make_service(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "tasks.json"
        return TaskService(TaskRepository(path)), path

    def test_adds_and_lists_open_tasks(self):
        service, _ = self.make_service()

        task = service.add_task("  Ship tests  ", priority="high", tags=["API", " api ", "", "Docs"])

        self.assertEqual(task.id, 1)
        self.assertEqual(task.title, "Ship tests")
        self.assertEqual(task.priority, "high")
        self.assertEqual(task.tags, ["api", "docs"])
        self.assertFalse(task.completed)
        self.assertEqual([item.title for item in service.list_tasks(status="open")], ["Ship tests"])

    def test_rejects_invalid_input(self):
        service, _ = self.make_service()

        with self.assertRaises(ValueError):
            service.add_task("")
        with self.assertRaises(ValueError):
            service.add_task("thing", priority="urgent")
        with self.assertRaises(ValueError):
            service.list_tasks(status="blocked")

    def test_completion_and_filters(self):
        service, _ = self.make_service()
        first = service.add_task("Write API", tags=["api"])
        second = service.add_task("Write docs", tags=["docs"])

        completed = service.complete_task(first.id)

        self.assertTrue(completed.completed)
        self.assertEqual([item.id for item in service.list_tasks(status="completed")], [first.id])
        self.assertEqual([item.id for item in service.list_tasks(status="open")], [second.id])
        self.assertEqual([item.id for item in service.list_tasks(tag="API")], [first.id])
        with self.assertRaises(KeyError):
            service.complete_task(999)

    def test_persists_and_reloads_tasks(self):
        service, path = self.make_service()
        service.add_task("Persist me", tags=["storage"])
        service.add_task("Second")

        reloaded = TaskService(TaskRepository(path))

        self.assertEqual([item.title for item in reloaded.list_tasks()], ["Persist me", "Second"])
        self.assertEqual(reloaded.add_task("Third").id, 3)


if __name__ == "__main__":
    unittest.main()
