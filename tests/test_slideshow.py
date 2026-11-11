from PySide6.QtTest import QTest

from civitai_widget.slideshow import Slideshow


def test_advances_and_rearms(qapp):
    show = Slideshow(1000)
    fired = []
    show.advance.connect(lambda: fired.append(1))
    show.restart()
    assert show.is_running()
    QTest.qWait(2300)
    assert len(fired) == 2
    assert show.is_running()


def test_hold_freezes_instead_of_resetting(qapp):
    show = Slideshow(1000)
    fired = []
    show.advance.connect(lambda: fired.append(1))
    show.restart()
    QTest.qWait(600)
    show.hold("user", True)
    assert not show.is_running()
    frozen = show.fraction()
    assert 0.45 < frozen < 0.9
    QTest.qWait(700)
    assert fired == []
    assert show.fraction() == frozen
    show.hold("user", False)
    QTest.qWait(600)
    assert len(fired) == 1


def test_all_holds_must_be_released(qapp):
    show = Slideshow(1000)
    show.restart()
    show.hold("user", True)
    show.hold("hover", True)
    show.hold("hover", False)
    assert not show.is_running()
    show.hold("user", False)
    assert show.is_running()


def test_restart_resets_progress(qapp):
    show = Slideshow(1000)
    show.restart()
    QTest.qWait(400)
    show.restart()
    assert show.fraction() < 0.15
