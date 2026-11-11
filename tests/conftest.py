import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["test"])
    yield app


def make_item(item_id, **extra):
    item = {
        "id": item_id,
        "type": "image",
        "url": f"https://image.example/abc/{item_id}/original=true/{item_id}.jpeg",
        "nsfw": False,
        "nsfwLevel": "None",
        "username": f"user{item_id}",
        "stats": {"likeCount": 1, "heartCount": 2, "laughCount": 3, "cryCount": 4, "commentCount": 99},
    }
    item.update(extra)
    return item
