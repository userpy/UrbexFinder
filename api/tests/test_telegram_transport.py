from unittest.mock import Mock
import pytest
from urbex.infrastructure.telegram import TelegramPhotos
from urbex.domain.rules import DomainError


def test_transient_failure_retried():
    transport = TelegramPhotos('test')
    transport._get_once = Mock(side_effect=[DomainError('temporary', 502), b'jpeg'])
    assert transport.get('file') == b'jpeg'
    assert transport._get_once.call_count == 2


def test_retry_bounded_and_missing_configuration_not_retried():
    for status, count in [(502, 2), (503, 1)]:
        transport = TelegramPhotos('test')
        transport._get_once = Mock(side_effect=DomainError('unavailable', status))
        with pytest.raises(DomainError):
            transport.get('file')
        assert transport._get_once.call_count == count
