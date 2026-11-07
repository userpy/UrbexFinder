from types import SimpleNamespace
from unittest.mock import Mock
from urbex.application.service import Service


def test_pending_places_filter_is_applied_with_owner_before_pagination():
    repo = Mock()
    service = Service(repo, Mock())
    expected = {'items': [], 'total': 0, 'page': 2}
    repo.list.return_value = expected
    result = service.personal(SimpleNamespace(id=17), 'places', 2, pending_only=True)
    repo.list.assert_called_once_with('places', {'author_id': 17, 'status': 'pending'}, 2)
    assert result == expected


def test_existing_personal_list_keeps_all_statuses():
    repo = Mock()
    Service(repo, Mock()).personal(SimpleNamespace(id=17), 'places', 1)
    repo.list.assert_called_once_with('places', {'author_id': 17}, 1)


def test_published_and_pending_lists_keep_owner_and_pagination():
    for status in ['published', 'pending']:
        repo = Mock()
        Service(repo, Mock()).personal(SimpleNamespace(id=17), 'places', 2, status=status)
        repo.list.assert_called_once_with('places', {'author_id': 17, 'status': status}, 2)
