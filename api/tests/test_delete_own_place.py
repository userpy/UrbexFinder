from unittest.mock import Mock
import pytest
from urbex.application.places import PlacesService
from urbex.domain.rules import Actor, DomainError


@pytest.mark.parametrize('status', ['pending', 'published'])
def test_owner_removes_place_without_destroying_references(status):
    repo = Mock()
    repo.get.return_value = {'author_id': 7, 'status': status}
    assert PlacesService(repo).remove_own(Actor(7, 'user'), 42) == {'ok': True}
    repo.get.assert_called_once_with('places', 42, lock=True)
    values = repo.update.call_args.args[2]
    assert values['status'] == 'rejected'
    assert values['reason'] == 'Удалено автором'
    repo.delete.assert_not_called()
    repo.audit.assert_called_once()


@pytest.mark.parametrize('role', ['user', 'moderator', 'admin'])
def test_owner_endpoint_rejects_other_users_places(role):
    repo = Mock()
    repo.get.return_value = {'author_id': 8, 'status': 'published'}
    with pytest.raises(DomainError) as error:
        PlacesService(repo).remove_own(Actor(7, role), 42)
    assert error.value.status == 404
    repo.update.assert_not_called()
    repo.audit.assert_not_called()
