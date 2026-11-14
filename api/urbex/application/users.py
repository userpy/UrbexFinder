from .ports import Repository, Passwords
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl
from urbex.domain.rules import Actor, DomainError


def public_user(u):
    return {k: u[k] for k in ('id', 'email', 'name', 'role', 'blocked')}


class Auth:
    def __init__(self, repo: Repository, config, passwords: Passwords):
        self.repo, self.config, self.passwords = repo, config, passwords

    def throttle(self, key):
        count = self.repo.rate_attempt(sha256(key.encode()).hexdigest())
        if count > 10:
            raise DomainError('Слишком много попыток. Повторите через 15 минут', 429)

    def register(self, data):
        if self.repo.list('users', {'email': data['email']})['total']:
            raise DomainError('Этот email уже зарегистрирован', 409)
        return self.repo.add('users', dict(email=data['email'], name=data['name'], password_hash=self.passwords.hash(data['password']), role='user'))

    def login(self, email, password, ip):
        self.throttle('ip:'+ip)
        self.throttle('email:'+email)
        users = self.repo.list('users', {'email': email})['items']
        user = users[0] if users else None
        if not self.passwords.verify(user['password_hash'] if user else None, password):
            raise DomainError('Неверный email или пароль', 401)
        if not user or user['blocked']:
            raise DomainError('Неверный email или пароль', 401)
        return user

    def start(self, user, previous=None):
        if previous:
            self.logout(previous)
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        self.repo.add('sessions', dict(token_hash=sha256(token.encode()).hexdigest(), csrf=csrf, user_id=user['id'],
            expires_at=datetime.now(timezone.utc)+timedelta(hours=self.config.session_hours)))
        return token, csrf

    def resolve(self, token):
        if not token:
            return None, None, None
        rows = self.repo.list('sessions', {'token_hash': sha256(token.encode()).hexdigest()})['items']
        if not rows or rows[0]['expires_at'] <= datetime.now(timezone.utc):
            return None, None, None
        session = rows[0]
        user = self.repo.get('users', session['user_id'])
        if user['blocked']:
            return None, None, None
        return Actor(user['id'], user['role']), session['csrf'], public_user(user)

    def logout(self, token):
        if token:
            self.repo.delete('sessions', {'token_hash': sha256(token.encode()).hexdigest()})

    def revoke_all(self, actor):
        self.repo.delete("sessions", {"user_id": actor.id})

    def manage_user(self, actor, id, data):
        actor.require('admin')
        if id == actor.id:
            raise DomainError('Нельзя изменить собственные права или заблокировать себя')
        target = self.repo.get('users', id, lock=True)
        if target.get('deleted'): raise DomainError('Пользователь удалён', 404)
        self.repo.update('users', id, data)
        self.repo.delete('sessions', {'user_id': id})
        self.repo.audit(actor.id, 'user.update', f'users:{id}', str(data))
        return {'ok': True}

    def telegram_begin(self, ip):
        if not self.config.telegram_bot_username:
            raise DomainError('Вход через Telegram не настроен',503)
        self.throttle('telegram:'+ip)
        browser, link = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        code = f'{secrets.randbelow(1000000):06d}'
        self.repo.add('telegram_logins', dict(browser_hash=sha256(browser.encode()).hexdigest(),
            link_hash=sha256(link.encode()).hexdigest(), code=code,
            expires_at=datetime.now(timezone.utc)+timedelta(minutes=5)))
        return browser, {'url':f'https://t.me/{self.config.telegram_bot_username}?start=login_{link}', 'code':code}

    def telegram_complete(self, browser):
        if not browser:raise DomainError('Начните вход через Telegram заново',401)
        rows=self.repo.list('telegram_logins',{'browser_hash':sha256(browser.encode()).hexdigest()})['items']
        if not rows:raise DomainError('Запрос входа не найден',401)
        challenge=self.repo.get('telegram_logins',rows[0]['id'],lock=True)
        if challenge['expires_at'] <= datetime.now(timezone.utc) or challenge['consumed']:
            raise DomainError('Срок подтверждения истёк. Начните вход заново.',410)
        if not challenge['confirmed']:return None
        user=self.repo.telegram_user(challenge['telegram_id'], challenge['display_name'], self.passwords.hash(secrets.token_urlsafe(48)))
        if user['blocked']:raise DomainError('Учётная запись заблокирована',403)
        self.repo.update('telegram_logins',challenge['id'],{'consumed':True})
        return user

    def telegram_mini_app(self, init_data, ip):
        if not self.config.telegram_bot_token:
            raise DomainError('Вход через Telegram не настроен',503)
        self.throttle('telegram-mini-app:'+ip)
        try:
            pairs=parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=32)
        except ValueError:
            raise DomainError('Некорректные данные Telegram Mini App',401) from None
        data=dict(pairs)
        if len(data) != len(pairs):
            raise DomainError('Некорректные данные Telegram Mini App',401)
        received_hash=data.pop('hash',None)
        if not received_hash or not re.fullmatch(r'[0-9a-f]{64}',received_hash):
            raise DomainError('Некорректные данные Telegram Mini App',401)
        data_check_string='\n'.join(f'{key}={value}' for key,value in sorted(data.items()))
        secret_key=hmac.new(b'WebAppData',self.config.telegram_bot_token.encode(),hashlib.sha256).digest()
        expected_hash=hmac.new(secret_key,data_check_string.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash,received_hash):
            raise DomainError('Подпись Telegram Mini App недействительна',401)
        try:
            auth_date=int(data['auth_date'])
            now=int(datetime.now(timezone.utc).timestamp())
            telegram_user=json.loads(data['user'])
            if not isinstance(telegram_user,dict):
                raise ValueError
            telegram_id=telegram_user['id']
            if (auth_date > now+30 or now-auth_date > 300
                    or isinstance(telegram_id,bool) or not isinstance(telegram_id,int) or telegram_id <= 0):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise DomainError('Данные Telegram Mini App истекли или некорректны',401) from None
        name=' '.join(part for part in (telegram_user.get('first_name'),telegram_user.get('last_name')) if isinstance(part,str)).strip()
        if not name and isinstance(telegram_user.get('username'),str):
            name=telegram_user['username']
        user=self.repo.telegram_user(telegram_id,name[:100] or f'Telegram {telegram_id}',
            self.passwords.hash(secrets.token_urlsafe(48)))
        if user['blocked']:
            raise DomainError('Учётная запись заблокирована',403)
        return user

    def delete_user(self, actor, id):
        actor.require('admin')
        if id == actor.id:
            raise DomainError('Нельзя удалить собственную учётную запись')
        target = self.repo.get('users', id, lock=True)
        if target.get('deleted'): return {'ok': True}
        self.repo.delete('sessions', {'user_id': id})
        self.repo.delete('favorites', {'user_id': id})
        self.repo.delete('itineraries', {'author_id': id})
        self.repo.update('users', id, dict(deleted=True, blocked=True, role='user',
            email=None, telegram_id=None, name='Удалённый пользователь',
            password_hash=self.passwords.hash(secrets.token_urlsafe(48))))
        self.repo.audit(actor.id, 'user.delete', f'users:{id}', 'Учётная запись удалена; общие материалы сохранены')
        return {'ok': True}
