from dataclasses import dataclass


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


@dataclass(frozen=True)
class Actor:
    id: int
    role: str

    def require(self, *roles: str):
        if self.role not in roles:
            raise DomainError('Недостаточно прав', 403)


def moderation_decision(status: str, reason: str):
    if status not in {'published', 'rejected', 'changes_requested'}:
        raise DomainError('Некорректное решение')
    if status != 'published' and len(reason.strip()) < 5:
        raise DomainError('Укажите причину (не менее 5 символов)')


def can_read(item: dict, actor: Actor | None):
    return (item['status'] == 'published' and item.get('nonexistent_reports_count', 0) < 10) or (actor and (
        item.get('author_id') == actor.id or actor.role in {'moderator', 'admin'}))
