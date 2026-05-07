"""tests/test_db_manager.py — db_manager 단위 테스트 (DB 불필요, 모킹)"""

from unittest.mock import MagicMock, patch, call
import pytest

from database.db_manager import get_or_create, bulk_insert


# ── get_or_create ─────────────────────────────────────────────

class TestGetOrCreate:
    def test_returns_existing_instance(self):
        session = MagicMock()
        existing = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = existing

        result, created = get_or_create(session, MagicMock, name="test")

        assert result is existing
        assert created is False

    def test_creates_new_instance_when_not_found(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None

        MockModel = MagicMock()
        new_instance = MagicMock()
        MockModel.return_value = new_instance

        result, created = get_or_create(session, MockModel, defaults={"grade": "C"}, name="new")

        assert created is True
        MockModel.assert_called_once_with(name="new", grade="C")
        session.add.assert_called_once_with(new_instance)
        session.flush.assert_called_once()

    def test_defaults_merged_with_kwargs(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None

        MockModel = MagicMock()
        get_or_create(session, MockModel, defaults={"url": "http://x.com"}, name="src")

        MockModel.assert_called_once_with(name="src", url="http://x.com")


# ── bulk_insert ───────────────────────────────────────────────

class TestBulkInsert:
    def test_adds_all_and_flushes(self):
        session = MagicMock()
        objects = [MagicMock(), MagicMock(), MagicMock()]

        bulk_insert(session, objects)

        session.add_all.assert_called_once_with(objects)
        session.flush.assert_called_once()

    def test_empty_list(self):
        session = MagicMock()
        bulk_insert(session, [])
        session.add_all.assert_called_once_with([])


# ── get_session context manager ───────────────────────────────

class TestGetSession:
    def test_commits_on_success(self):
        mock_session = MagicMock()
        mock_factory = MagicMock(return_value=mock_session)

        with patch("database.db_manager._SessionFactory", mock_factory):
            from database.db_manager import get_session
            with get_session() as s:
                assert s is mock_session

        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_rolls_back_on_exception(self):
        mock_session = MagicMock()
        mock_factory = MagicMock(return_value=mock_session)

        with patch("database.db_manager._SessionFactory", mock_factory):
            from database.db_manager import get_session
            with pytest.raises(ValueError):
                with get_session():
                    raise ValueError("boom")

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()
