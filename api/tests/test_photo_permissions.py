from unittest.mock import Mock
import pytest
from urbex.application.places import PlacesService
from urbex.domain.rules import Actor, DomainError


@pytest.mark.parametrize('role,owner,allowed', [('user',7,True),('user',8,False),('moderator',8,True),('admin',8,True)])
def test_upload_requires_place_owner_or_staff(role, owner, allowed):
    repo, storage = Mock(), Mock()
    repo.get.return_value = {'author_id':owner, 'status':'published'}
    repo.list.return_value = {'total':0}
    service = PlacesService(repo, storage)
    if allowed:
        service.photo(Actor(7,role),42,b'jpeg')
        assert repo.add.call_args.args[1]['author_id'] == 7
        storage.put.assert_called_once()
    else:
        with pytest.raises(DomainError) as error: service.photo(Actor(7,role),42,b'jpeg')
        assert error.value.status == 403
        storage.put.assert_not_called()


@pytest.mark.parametrize('role,owner,photo_owner,allowed', [
    ('user',7,7,True),('user',7,8,False),('user',8,7,False),
    ('moderator',8,None,True),('admin',8,8,True),
])
def test_photo_delete_permissions(role,owner,photo_owner,allowed):
    repo=Mock()
    repo.get.side_effect=[{'place_id':42,'author_id':photo_owner},{'author_id':owner}]
    service=PlacesService(repo)
    if allowed:
        assert service.delete_photo(Actor(7,role),1)=={'ok':True}
        assert repo.update.call_args.args[2]['status']=='rejected'
    else:
        with pytest.raises(DomainError) as error: service.delete_photo(Actor(7,role),1)
        assert error.value.status==403
        repo.update.assert_not_called()


def test_guest_sees_only_published_photos_and_member_gets_scoped_filter():
    repo=Mock(); repo.get.return_value={'status':'published','author_id':7}
    service=PlacesService(repo)
    service.related('photos',42,None)
    repo.list.assert_called_with('photos',{'place_id':42,'status':'published'},1)
    service.related('photos',42,Actor(7,'user'))
    repo.list.assert_called_with('photos',{'place_id':42,'visible_to':7,'staff':False},1)
